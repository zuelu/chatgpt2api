from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from PIL import Image

from services.image_input_service import prepare_image_references
from services.protocol import conversation, openai_v1_image_edit as edits
import services.official_image_service as official
from services.account_service import AccountService
from services.storage.json_storage import JSONStorageBackend
from services.image_task_service import ImageTaskService
from test.test_image_task_service import OWNER, wait_for_task


def raster(format='PNG', animated=False):
    output = io.BytesIO()
    first = Image.new('RGBA', (32, 24), (240, 20, 10, 255))
    options = {'save_all': True, 'append_images': [Image.new('RGBA', (32, 24), (0, 30, 220, 255))], 'duration': 100, 'loop': 0} if animated else {}
    if format == 'WEBP':options['lossless'] = True
    first.save(output, format=format, **options)
    return output.getvalue()


class ImageReferencesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.accounts = AccountService(JSONStorageBackend(self.root/'accounts.json'))
        self.accounts.add_account_items([{'access_token': 'api:test', 'api_key': 'fake-key', 'type': 'API', 'source_type': 'api', 'quota': 0}])

    def test_gif_webp_and_apng_references_use_first_frame_even_when_mislabeled(self):
        for format in ('GIF', 'WEBP', 'PNG'):
            with self.subTest(format=format):
                data = raster(format, True)
                prepared, notes = prepare_image_references([(data, 'product.jpg', 'image/jpeg')])
                self.assertEqual(prepared[0][1:], ('product.png', 'image/png'))
                self.assertEqual(notes[0]['code'], 'reference_first_frame')
                self.assertEqual(notes[0]['source_frames'], 2)
                self.assertEqual(notes[0]['selected_frame'], 0)
                with Image.open(io.BytesIO(prepared[0][0])) as result:
                    self.assertEqual(result.format, 'PNG');self.assertEqual(result.n_frames, 1)
                    self.assertEqual(result.convert('RGB').getpixel((5, 5)), (240, 20, 10))
                with Image.open(io.BytesIO(data)) as original:self.assertEqual(original.n_frames, 2)

    def test_compatible_still_references_preserve_bytes_and_correct_mime(self):
        for format in ('PNG', 'JPEG', 'WEBP'):
            with self.subTest(format=format):
                if format == 'JPEG':
                    out=io.BytesIO();Image.new('RGB',(20,20),'green').save(out,format='JPEG');data=out.getvalue()
                else:data=raster(format)
                prepared, notes = prepare_image_references([(data, 'product', 'wrong/mime')])
                self.assertEqual(prepared[0][0], data);self.assertEqual(notes, [])
                self.assertEqual(prepared[0][2], Image.MIME[format])

    def test_static_gif_and_bmp_are_converted_for_upstream_compatibility(self):
        for format in ('GIF', 'BMP'):
            prepared, notes = prepare_image_references([(raster(format), 'reference', 'image/'+format.lower())])
            self.assertTrue(prepared[0][0].startswith(b'\x89PNG'))
            self.assertEqual(notes[0]['code'], 'reference_png')

    def test_first_frame_transparency_and_dimensions_are_preserved(self):
        out=io.BytesIO();first=Image.new('RGBA',(20,30),(0,0,0,0));first.putpixel((5,5),(255,0,0,255))
        second=Image.new('RGBA',(20,30),(0,0,255,255));first.save(out,format='PNG',save_all=True,append_images=[second],duration=100)
        prepared,_=prepare_image_references([(out.getvalue(),'reference.png','image/png')])
        with Image.open(io.BytesIO(prepared[0][0])) as result:
            self.assertEqual(result.size,(20,30));self.assertEqual(result.getpixel((0,0))[3],0)
            self.assertEqual(result.getpixel((5,5)),(255,0,0,255))

    def test_invalid_or_svg_inputs_fail_before_account_acquisition(self):
        for data,code in ((b'invalid','invalid_reference_image'),(b'<svg/>','svg_edit_input_unsupported')):
            with self.subTest(code=code),mock.patch('services.account_service.account_service',self.accounts),mock.patch.object(self.accounts,'get_available_access_token') as acquire:
                with self.assertRaises(HTTPException) as error:
                    edits.handle({'model':'api-gpt-image-2.6-flare','prompt':'poster','images':[(data,'reference.png','image/png')]})
                self.assertEqual(error.exception.detail['error']['code'],code);acquire.assert_not_called()

    def test_official_edit_normalizes_animated_input_without_changing_requested_output(self):
        for output in ('png','gif'):
            captures=[]
            def upstream(client,payload,images,masks):
                captures.append((payload,images))
                with Image.open(io.BytesIO(images[0][0])) as image:self.assertEqual(image.n_frames,1)
                return {'data':[{'b64_json':base64.b64encode(raster('GIF' if output=='gif' else 'PNG', output=='gif')).decode()}]}
            with self.subTest(output=output),mock.patch('services.account_service.account_service',self.accounts),mock.patch.object(official.OfficialImagesClient,'images',upstream),mock.patch.object(conversation,'save_image_bytes',return_value='https://test/result.'+output):
                result=edits.handle({'model':'api-gpt-image-2.6-flare','prompt':'poster','output_format':output,'images':[(raster('WEBP',True),'product.jpg','image/jpeg')]})
            self.assertEqual(captures[0][0]['model'],'gpt-image-2.6-flare')
            self.assertEqual(captures[0][0]['output_format'],output)
            self.assertEqual(result['input_adjustments'][0]['code'],'reference_first_frame')
            self.assertEqual(result['data'][0]['mime_type'],'image/'+output)
        self.assertEqual(self.accounts.list_accounts()[0]['image_inflight'],0)

    def test_codex_edit_normalizes_before_encoding_and_mask_compositing(self):
        def outputs(request):
            with Image.open(io.BytesIO(base64.b64decode(request.images[0]))) as image:
                self.assertEqual(image.n_frames,1);self.assertEqual(image.format,'PNG')
            return iter([conversation.ImageOutput(kind='result',model=request.model,index=1,total=1,data=[{'url':'https://test/image.png'}])])
        with mock.patch.object(edits,'stream_image_outputs_with_pool',outputs):
            result=edits.handle({'model':'codex-gpt-image-2.6','prompt':'poster','images':[(raster('GIF',True),'product.gif','image/gif')]})
        self.assertEqual(result['input_adjustments'][0]['source_frames'],2)

    def test_chat_image_encoder_also_uses_a_still_frame(self):
        encoded=conversation.encode_images([(raster('PNG',True),'product.png','image/png')])
        with Image.open(io.BytesIO(base64.b64decode(encoded[0]))) as image:self.assertEqual(image.n_frames,1)

    def test_async_adjustments_are_public_persisted_and_logged(self):
        notes=[{'index':0,'code':'reference_first_frame','source_format':'gif','source_frames':2,'selected_frame':0,'output_format':'png'}]
        def handler(payload):
            payload['progress_callback']('image_stream_resolve_start')
            return {'data':[{'url':'https://test/out.png'}],'input_adjustments':notes}
        service=ImageTaskService(self.root/'tasks.json',edit_handler=handler)
        with mock.patch('services.image_task_service.log_service.add') as log:
            service.submit_edit(OWNER,client_task_id='animated-ref',prompt='poster',model='api-gpt-image-2.6-flare',size=None,images=[(raster('GIF',True),'reference.gif','image/gif')])
            task=wait_for_task(service,OWNER,'animated-ref','success')
        self.assertEqual(task['input_adjustments'],notes)
        restored=ImageTaskService(self.root/'tasks.json')
        self.assertEqual(restored.list_tasks(OWNER,['animated-ref'])['items'][0]['input_adjustments'],notes)
        self.assertEqual(log.call_args.args[2]['input_adjustments'],notes)

    def test_sync_conversion_is_recorded_in_success_log(self):
        from services.log_service import LoggedCall
        notes=[{'index':0,'code':'reference_first_frame'}]
        with mock.patch('services.log_service.log_service.add') as log:
            LoggedCall(OWNER,'/v1/images/edits','api-gpt-image-2.6-flare','test').log('done',{'data':[],'input_adjustments':notes})
        self.assertEqual(log.call_args.args[2]['input_adjustments'],notes)


if __name__=='__main__':unittest.main()
