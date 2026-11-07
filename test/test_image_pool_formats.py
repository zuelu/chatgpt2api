from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import services.official_image_service as official
from services.account_service import AccountService
from services.storage.json_storage import JSONStorageBackend
from services.protocol import conversation, openai_v1_image_generations as generations, openai_v1_image_edit as edits
from services.image_storage_service import ImageStorageService
from services.image_task_service import ImageTaskService
from utils.image_formats import image_media_type, image_extension, svg_root
from test.test_official_images import encoded_image
from test.test_image_task_service import OWNER, wait_for_task

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80"><defs><linearGradient id="g"><stop stop-color="orange"/></linearGradient></defs><circle cx="50" cy="40" r="30" fill="url(#g)"/></svg>'


class ImagePoolFormatsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.accounts = AccountService(JSONStorageBackend(self.root / 'accounts.json'))
        self.accounts.add_account_items([
            {'access_token': 'api:' + name, 'api_key': 'fake-key-' + name, 'source_type': 'api', 'type': 'API', 'quota': 0}
            for name in ('a', 'b', 'c')
        ])

    def response(self, data=SVG):
        return {'data': [{'b64_json': base64.b64encode(data).decode()}]}

    def test_round_robin_order_survives_exclusion_and_respects_capacity(self):
        selected = []
        for _ in range(4):
            token = self.accounts.get_available_access_token(source_type='api')
            selected.append(token)
            self.accounts.mark_image_result(token, True)
        self.assertEqual(selected, ['api:a', 'api:b', 'api:c', 'api:a'])
        token = self.accounts.get_available_access_token(source_type='api', excluded_tokens={'api:a'})
        self.assertEqual(token, 'api:b')
        self.accounts.release_image_slot(token)

    def test_codex_traffic_does_not_reset_api_round_robin(self):
        self.accounts.add_account_items([{'access_token': 'codex-a', 'source_type': 'codex', 'type': 'Pro', 'quota': 10}])
        first = self.accounts.get_available_access_token(source_type='api')
        self.accounts.release_image_slot(first)
        with mock.patch.object(self.accounts, 'fetch_remote_info', side_effect=lambda token, event: self.accounts.get_account(token)):
            codex = self.accounts.get_available_access_token(source_type='codex')
        self.accounts.release_image_slot(codex)
        second = self.accounts.get_available_access_token(source_type='api')
        self.accounts.release_image_slot(second)
        self.assertEqual((first, second), ('api:a', 'api:b'))

    def test_quota_and_auth_errors_fail_over_once_per_api_account(self):
        attempts = []
        def upstream(client, body, images, masks):
            attempts.append((client.key, body['model'], body['output_format']))
            if client.key.endswith('a'):
                raise official.OfficialAPIError('Quota exceeded', 429, 'insufficient_quota')
            if client.key.endswith('b'):
                raise official.OfficialAPIError('Invalid key', 401, 'invalid_api_key')
            return self.response(encoded_image())
        progress = []
        with mock.patch('services.account_service.account_service', self.accounts), mock.patch.object(official.OfficialImagesClient, 'images', upstream), mock.patch.object(conversation, 'save_image_bytes', return_value='https://test/out.gif'):
            result = generations.handle({'model': 'codex-gpt-image-2.6', 'output_format': 'gif', 'prompt': 'bounce', 'progress_callback': progress.append})
        self.assertEqual([item[0] for item in attempts], ['fake-key-a', 'fake-key-b', 'fake-key-c'])
        self.assertTrue(all(item[1:] == ('gpt-image-2.6-sunburst', 'gif') for item in attempts))
        self.assertEqual(result['data'][0]['mime_type'], 'image/gif')
        self.assertEqual(progress, ['getting_account', 'image_stream_resolve_start'] * 3 + ['receiving_image'])
        self.assertEqual([a['fail'] for a in self.accounts.list_accounts()], [1, 1, 0])
        self.assertEqual([a['success'] for a in self.accounts.list_accounts()], [0, 0, 1])
        self.assertTrue(all(a['image_inflight'] == 0 for a in self.accounts.list_accounts()))

    def test_exhausted_pool_returns_original_error_without_reusing_accounts(self):
        with mock.patch('services.account_service.account_service', self.accounts), mock.patch.object(official.OfficialImagesClient, 'images', side_effect=official.OfficialAPIError('Quota exhausted', 429, 'insufficient_quota')) as upstream:
            with self.assertRaises(conversation.ImageGenerationError) as caught:
                generations.handle({'output_format': 'gif', 'prompt': 'bounce'})
        self.assertEqual(upstream.call_count, 3)
        self.assertEqual(caught.exception.code, 'insufficient_quota')
        self.assertTrue(all(a['image_inflight'] == 0 for a in self.accounts.list_accounts()))

    def test_policy_and_invalid_requests_are_not_retried(self):
        for code in ('content_policy_violation', 'invalid_request_error'):
            with self.subTest(code=code), mock.patch('services.account_service.account_service', self.accounts), mock.patch.object(official.OfficialImagesClient, 'images', side_effect=official.OfficialAPIError('Rejected', 400, code)) as upstream:
                with self.assertRaises(conversation.ImageGenerationError):
                    generations.handle({'output_format': 'svg', 'prompt': 'test'})
                self.assertEqual(upstream.call_count, 1)

    def test_svg_model_selection_is_only_added_after_explicit_parameter_rejection(self):
        calls = []
        def upstream(client, body, images, masks):
            calls.append(body.copy())
            if 'svg' not in body:
                raise official.OfficialAPIError("SVG generation requires 'svg.model'.", 400, 'missing_required_parameter')
            return {**self.response(), 'svg_usage': {'model': 'gpt-6.1-sol', 'total_tokens': 20}}
        with mock.patch('services.account_service.account_service', self.accounts), mock.patch.object(official.OfficialImagesClient, 'images', upstream), mock.patch.object(conversation, 'save_image_bytes', return_value='https://test/out.svg'):
            result = generations.handle({'model': 'codex-gpt-image-2.6', 'output_format': 'svg', 'prompt': 'icon'})
        self.assertEqual(len(calls), 2)
        self.assertNotIn('svg', calls[0])
        self.assertEqual(calls[1]['svg']['model'], 'gpt-6.1-sol')
        self.assertEqual(result['svg_usage']['total_tokens'], 20)
        self.assertEqual(result['data'][0]['mime_type'], 'image/svg+xml')
        self.assertEqual(base64.b64decode(result['data'][0]['b64_json']), SVG)
        self.assertEqual(self.accounts.list_accounts()[0]['success'], 1)
        self.assertEqual(self.accounts.list_accounts()[0]['fail'], 0)

    def test_static_reference_can_generate_gif_with_native_edit_endpoint(self):
        with mock.patch('services.account_service.account_service', self.accounts), mock.patch.object(official.OfficialImagesClient, 'images', return_value=self.response(encoded_image())) as upstream, mock.patch.object(conversation, 'save_image_bytes', return_value='https://test/out.gif'):
            edits.handle({'model': 'codex-gpt-image-2.6', 'output_format': 'gif', 'frame_count': 4, 'frame_duration_ms': 100, 'prompt': 'animate', 'images': [(encoded_image(False), 'reference.png', 'image/png')]})
        payload, images, masks = upstream.call_args.args
        self.assertEqual(payload['model'], 'gpt-image-2.6-sunburst')
        self.assertEqual(payload['frame_count'], 4)
        self.assertEqual(payload['frame_duration_ms'], 100)
        self.assertEqual(images[0][1], 'reference.png')
        self.assertIsNone(masks)

    def test_svg_constraints_and_masks_fail_before_any_upstream_call(self):
        bodies = [
            {'output_format': 'svg', 'n': 2},
            {'output_format': 'svg', 'stream': True},
            {'output_format': 'svg', 'output_compression': 80},
            {'output_format': 'gif', 'frame_count': 17},
            {'output_format': 'gif', 'mask': [b'mask']},
        ]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(HTTPException):
                official.validate_image_options(body)
        with self.assertRaises(HTTPException):
            official.validate_image_options({'output_format': 'svg'}, editing=True)
        with self.assertRaises(HTTPException):
            official.prepare_image_references([(SVG, 'test.svg', 'image/svg+xml')])

    def test_svg_storage_preserves_vector_bytes_dimensions_and_preview(self):
        with mock.patch('services.image_storage_service.config') as config:
            config.images_dir = self.root / 'images'; config.base_url = 'https://test'
            config.get_image_storage_settings.return_value = {'mode': 'local'}
            storage = ImageStorageService(self.root / 'index.json')
            saved = storage.save(SVG)
            self.assertTrue(saved.rel.endswith('.svg'))
            self.assertEqual(storage.get_bytes(saved.rel), SVG)
            listed = storage.list_items('https://test')[0]
            self.assertEqual((listed['width'], listed['height']), (100, 80))
            from services import image_service
            with mock.patch.object(image_service, 'image_storage_service', storage), mock.patch.object(image_service, 'config', config):
                preview = image_service.get_thumbnail_response(saved.rel)
                self.assertEqual(preview.media_type, 'image/svg+xml')
                self.assertIn('sandbox', preview.headers['content-security-policy'])
                download = image_service.get_image_download_response(saved.rel)
                self.assertIn('.svg', download.headers['content-disposition'])

    def test_active_external_and_embedded_svg_content_is_rejected(self):
        bad = [
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            b'<svg onload="alert(1)"/>',
            b'<svg><image href="data:image/png;base64,AAAA"/></svg>',
            b'<svg><use href="https://example.org/image.svg#x"/></svg>',
            b'<svg><rect fill="url(https://example.org/x)"/></svg>',
            b'<svg><style>@import "https://example.org/a.css";</style></svg>',
            b'<!DOCTYPE svg [<!ENTITY x "test">]><svg>&x;</svg>',
            b'<svg><foreignObject><div/></foreignObject></svg>',
            b'<?xml-stylesheet href="https://example.org/style.css"?><svg/>',
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                svg_root(data)
        self.assertEqual(image_media_type(SVG), 'image/svg+xml')
        self.assertEqual(image_extension(SVG), '.svg')

    def test_codex_quota_failure_and_empty_output_switch_to_next_eligible_account(self):
        for failure in ('quota', 'empty'):
            with self.subTest(failure=failure):
                calls = []; mark = mock.Mock()
                def stream(backend, request, index, total):
                    calls.append(backend.access_token)
                    if backend.access_token == 'codex-a':
                        if failure == 'quota':
                            raise conversation.ImageGenerationError('Image usage limit reached', status_code=429, code='rate_limit_exceeded')
                        return iter([])
                    return iter([conversation.ImageOutput(kind='result', model=request.model, index=index, total=total, data=[{'url': 'https://test/out.png'}])])
                account = mock.Mock()
                account.get_available_access_token.side_effect = ['codex-a', 'codex-b']
                account.get_account.return_value = {}
                account.mark_image_result = mark
                with mock.patch.object(conversation, 'account_service', account), mock.patch.object(conversation, 'OpenAIBackendAPI', side_effect=lambda access_token: mock.Mock(access_token=access_token)), mock.patch.object(conversation, 'stream_codex_image_outputs', stream):
                    result = conversation._generate_single_image(conversation.ConversationRequest(model='codex-gpt-image-2.6'), 1, 1)
                self.assertEqual(calls, ['codex-a', 'codex-b'])
                self.assertEqual(result[0].kind, 'result')
                self.assertEqual(mark.call_args_list, [mock.call('codex-a', False), mock.call('codex-b', True)])
                self.assertEqual(account.get_available_access_token.call_args.kwargs['source_type'], 'codex')
                self.assertEqual(account.get_available_access_token.call_args.kwargs['excluded_tokens'], {'codex-a', 'codex-b'})

    def test_multipart_edit_parser_keeps_native_format_and_frame_options(self):
        from api.image_inputs import parse_image_edit_request, read_image_sources
        app = FastAPI()
        @app.post('/edit')
        async def parse(request: Request):
            payload, sources, masks = await parse_image_edit_request(request)
            images = await read_image_sources(sources)
            return {**payload, 'images': len(images), 'masks': len(masks)}
        client = TestClient(app)
        response = client.post('/edit', data={'prompt': 'animate', 'model': 'codex-gpt-image-2.6', 'output_format': 'gif', 'frame_count': '4', 'frame_duration_ms': '100'}, files={'image': ('reference.png', encoded_image(False), 'image/png')})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload['model'], 'api-gpt-image-2.6-sunburst')
        self.assertEqual(payload['output_format'], 'gif')
        self.assertEqual(payload['frame_count'], 4)
        self.assertEqual(payload['frame_duration_ms'], 100)
        self.assertEqual(payload['images'], 1)
        response = client.post('/edit', data={'prompt': 'edit', 'output_format': 'svg'}, files={'image': ('reference.png', encoded_image(False), 'image/png')})
        self.assertEqual(response.status_code, 400)

    def test_async_task_persists_auto_route_and_gif_edit_settings(self):
        captures = []
        def handler(payload):
            captures.append(dict(payload))
            return {'data': [{'url': 'https://test/out.gif'}]}
        service = ImageTaskService(self.root / 'tasks.json', generation_handler=handler, edit_handler=handler)
        service.submit_edit(OWNER, client_task_id='gif-edit', prompt='animate', model='codex-gpt-image-2.6', size='512x512', output_format='gif', frame_count=4, frame_duration_ms=100, images=[(encoded_image(False), 'reference.png', 'image/png')])
        task = wait_for_task(service, OWNER, 'gif-edit', 'success')
        self.assertEqual(task['model'], 'api-gpt-image-2.6-sunburst')
        self.assertEqual(task['output_format'], 'gif')
        self.assertEqual(captures[0]['frame_count'], 4)
        self.assertEqual(captures[0]['frame_duration_ms'], 100)


if __name__ == '__main__':
    unittest.main()
