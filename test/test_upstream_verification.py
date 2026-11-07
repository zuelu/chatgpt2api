from __future__ import annotations

import unittest
from contextlib import nullcontext
from unittest import mock

from services.openai_backend_api import OpenAIBackendAPI, UpstreamVerificationRequiredError
from services.protocol import conversation
from services.log_service import _image_error_response


def backend_for_prepare(data):
    backend = object.__new__(OpenAIBackendAPI)
    backend.base_url = 'https://chatgpt.test'
    backend.access_token = 'test-token'
    backend.user_agent = 'test-agent'
    backend.pow_script_sources = []
    backend.pow_data_build = ''
    backend._headers = mock.Mock(return_value={})
    backend.session = mock.Mock()
    backend.session.post.side_effect = [
        mock.Mock(status_code=200, json=mock.Mock(return_value=data)),
        mock.Mock(status_code=200, json=mock.Mock(return_value={'token': 'final-token'})),
    ]
    return backend


class UpstreamVerificationTests(unittest.TestCase):
    def test_required_interactive_checks_stop_before_finalize(self):
        for name in ['turnstile', 'so', 'arkose']:
            with self.subTest(challenge=name):
                backend = backend_for_prepare({name: {'required': True}})
                with mock.patch('services.openai_backend_api.build_proof_token') as proof:
                    with self.assertRaises(UpstreamVerificationRequiredError) as caught:
                        backend._get_chat_requirements()
                self.assertEqual(caught.exception.challenges, (name,))
                self.assertEqual(caught.exception.code, 'upstream_verification_required')
                self.assertEqual(backend.session.post.call_count, 1)
                proof.assert_not_called()

    def test_combined_challenges_are_reported_without_payloads(self):
        backend = backend_for_prepare({
            'turnstile': {'required': True, 'dx': 'private-challenge-data'},
            'so': {'required': True, 'collector_dx': 'private-environment-data'},
        })
        with self.assertRaises(UpstreamVerificationRequiredError) as caught:
            backend._get_chat_requirements()
        self.assertEqual(caught.exception.challenges, ('turnstile', 'so'))
        self.assertNotIn('private-', str(caught.exception))
        self.assertNotIn('private-', str(caught.exception.to_openai_error()))

    def test_requests_without_interactive_verification_still_finalize(self):
        backend = backend_for_prepare({
            'prepare_token': 'prepare-token',
            'turnstile': {'required': False}, 'so': {'required': False},
            'proofofwork': {'required': True, 'seed': 'seed', 'difficulty': 'ff'},
        })
        with mock.patch('services.openai_backend_api.build_proof_token', return_value='proof-token'):
            result = backend._get_chat_requirements()
        self.assertEqual(result.token, 'final-token')
        self.assertEqual(result.proof_token, 'proof-token')
        self.assertEqual(backend.session.post.call_count, 2)
        self.assertEqual(backend.session.post.call_args.kwargs['json'], {
            'prepare_token': 'prepare-token', 'proof_token': 'proof-token', 'turnstile_token': '',
        })

    def test_unverified_edit_does_not_upload_reference_images(self):
        backend = object.__new__(OpenAIBackendAPI)
        backend.access_token = 'test-token'
        backend._report_progress = mock.Mock()
        backend._bootstrap = mock.Mock()
        backend._get_chat_requirements = mock.Mock(side_effect=UpstreamVerificationRequiredError(['so']))
        backend._upload_image = mock.Mock()
        backend._prepare_image_conversation = mock.Mock()
        with self.assertRaises(UpstreamVerificationRequiredError):
            list(backend._stream_picture_conversation('edit', 'gpt-image-2.5', ['sample-image']))
        backend._upload_image.assert_not_called()
        backend._prepare_image_conversation.assert_not_called()

    def test_image_pool_preserves_verification_code_when_eligible_pool_is_exhausted(self):
        account = conversation.account_service
        backend = mock.Mock()
        error = UpstreamVerificationRequiredError(['turnstile', 'so'])
        with (
            mock.patch.object(account, 'get_available_access_token', side_effect=['test-token', RuntimeError('no available image quota')]) as get_token,
            mock.patch.object(account, 'get_account', return_value={'email': 'test@example.test'}),
            mock.patch.object(account, 'mark_image_result') as mark,
            mock.patch.object(account, 'refresh_access_token') as refresh,
            mock.patch.object(conversation, 'OpenAIBackendAPI', return_value=backend),
            mock.patch.object(conversation, 'stream_image_outputs', side_effect=error),
        ):
            with self.assertRaises(conversation.ImageGenerationError) as caught:
                conversation._generate_single_image(conversation.ConversationRequest(model='gpt-image-2.5'), 1, 1)
        self.assertEqual(caught.exception.code, 'upstream_verification_required')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(get_token.call_count, 2)
        mark.assert_called_once_with('test-token', False)
        refresh.assert_not_called()
        backend.close.assert_called_once()
        response = _image_error_response(caught.exception)
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'upstream_verification_required', response.body)

    def test_bound_image_preserves_verification_error_and_binding_identity(self):
        account = conversation.account_service
        request = conversation.ConversationRequest(
            model='gpt-image-2.5', retain_conversation=True,
            provider_binding_id='binding', provider_account_identity='account',
            client_conversation_id='client-conversation',
        )
        with (
            mock.patch.object(account, 'get_bound_account_identity', return_value='account'),
            mock.patch.object(account, 'acquire_bound_image_access_token', return_value='test-token'),
            mock.patch.object(account, 'get_account', return_value={}),
            mock.patch.object(account, 'conversation_binding_lock', return_value=nullcontext()),
            mock.patch.object(account, 'mark_image_result'),
            mock.patch.object(account, 'release_image_slot'),
            mock.patch.object(conversation, 'OpenAIBackendAPI'),
            mock.patch.object(conversation, 'stream_image_outputs', side_effect=UpstreamVerificationRequiredError(['so'])),
        ):
            with self.assertRaises(conversation.ImageGenerationError) as caught:
                conversation._generate_bound_single_image(request, 1, 1)
        self.assertEqual(caught.exception.code, 'upstream_verification_required')
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.provider_binding_id, 'binding')
        self.assertEqual(caught.exception.provider_account_identity, 'account')


if __name__ == '__main__':
    unittest.main()
