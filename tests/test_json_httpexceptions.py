import json

import pytest
from mock import Mock, patch

from nefertari import json_httpexceptions as jsonex
from nefertari.renderers import _JSONEncoder


class TestJSONHTTPExceptionsModule(object):

    def test_includeme(self):
        config = Mock()
        jsonex.includeme(config)
        config.add_view.assert_called_once_with(
            view=jsonex.httperrors,
            context=jsonex.http_exc.HTTPError)

    @patch.object(jsonex, 'traceback')
    def test_add_stack(self, mock_trace):
        mock_trace.format_stack.return_value = ['foo', 'bar']
        assert jsonex.add_stack() == 'foobar'

    def test_create_json_response(self):
        request = Mock(
            url='http://example.com',
            client_addr='127.0.0.1',
            remote_addr='127.0.0.2')
        obj = Mock(
            status_int=401,
            location='http://example.com/api')
        obj2 = jsonex.create_json_response(
            obj, request, encoder=_JSONEncoder,
            status_code=402, explanation='success',
            message='foo', title='bar')
        assert obj2.content_type == 'application/json'
        assert isinstance(obj2.body, basestring)
        body = json.loads(obj2.body)
        assert body.keys() == [
            'remote_addr', 'status_code', 'explanation', 'title',
            'message', 'id', 'timestamp', 'request_url', 'client_addr'
        ]
        assert body['remote_addr'] == '127.0.0.2'
        assert body['client_addr'] == '127.0.0.1'
        assert body['status_code'] == 402
        assert body['explanation'] == 'success'
        assert body['title'] == 'bar'
        assert body['message'] == 'foo'
        assert body['id'] == 'api'
        assert body['request_url'] == 'http://example.com'

    @patch.object(jsonex, 'add_stack')
    def test_create_json_response_obj_properties(self, mock_stack):
        mock_stack.return_value = 'foo'
        obj = Mock(
            status_int=401,
            location='http://example.com/api',
            status_code=402, explanation='success',
            message='foo', title='bar')
        obj2 = jsonex.create_json_response(
            obj, None, encoder=_JSONEncoder)
        body = json.loads(obj2.body)
        assert body['status_code'] == 402
        assert body['explanation'] == 'success'
        assert body['title'] == 'bar'
        assert body['message'] == 'foo'
        assert body['id'] == 'api'

    @patch.object(jsonex, 'add_stack')
    def test_create_json_response_stack_calls(self, mock_stack):
        mock_stack.return_value = 'foo'
        obj = Mock(status_int=401, location='http://example.com/api')
        jsonex.create_json_response(obj, None, encoder=_JSONEncoder)
        assert mock_stack.call_count == 0

        obj = Mock(status_int=500, location='http://example.com/api')
        jsonex.create_json_response(obj, None, encoder=_JSONEncoder)
        mock_stack.assert_called_with()
        assert mock_stack.call_count == 1

        obj = Mock(status_int=401, location='http://example.com/api')
        jsonex.create_json_response(
            obj, None, encoder=_JSONEncoder, show_stack=True)
        mock_stack.assert_called_with()
        assert mock_stack.call_count == 2

        obj = Mock(status_int=401, location='http://example.com/api')
        jsonex.create_json_response(
            obj, None, encoder=_JSONEncoder, log_it=True)
        mock_stack.assert_called_with()
        assert mock_stack.call_count == 3

    def test_exception_response(self):
        jsonex.STATUS_MAP[12345] = lambda x: x + 3
        assert jsonex.exception_response(12345, x=1) == 4
        with pytest.raises(KeyError):
            jsonex.exception_response(3123123123123123)
        jsonex.STATUS_MAP.pop(12345, None)

    def test_status_map(self):
        assert list(sorted(jsonex.STATUS_MAP.keys())) == [
            200, 201, 202, 203, 204, 205, 206,
            300, 301, 302, 303, 304, 305, 307,
            400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410,
            411, 412, 413, 414, 415, 416, 417, 422, 423, 424,
            500, 501, 502, 503, 504, 505, 507
        ]
        for code_exc in jsonex.STATUS_MAP.values():
            assert hasattr(jsonex, code_exc.__name__)

    @patch.object(jsonex, 'create_json_response')
    def test_httperrors(self, mock_create):
        jsonex.httperrors({'foo': 'bar'}, 1)
        mock_create.assert_called_once_with({'foo': 'bar'}, request=1)

    @patch.object(jsonex, 'create_json_response')
    def test_jhttpcreated(self, mock_create):
        resp = jsonex.JHTTPCreated(
            resource={'foo': 'bar'},
            location='http://example.com/1',
            encoder=1)
        mock_create.assert_called_once_with(
            resp, data={'foo': 'bar', 'self': 'http://example.com/1'},
            encoder=1)

    @patch.object(jsonex, 'apply_privacy')
    @patch.object(jsonex, 'create_json_response')
    def test_jhttpcreated_privacy_applied(self, mock_create, mock_priv):
        wrapper = Mock()
        mock_priv.return_value = wrapper
        wrapper.return_value = {'foo': 'bar', 'self': 'http://example.com/1'}
        request = Mock()
        request.registry._root_resources = {'foo': Mock(auth=True)}
        resp = jsonex.JHTTPCreated(
            resource={'foo': 'bar', 'zoo': 1},
            location='http://example.com/1',
            encoder=1,
            request=request)
        mock_create.assert_called_once_with(
            resp, data={'foo': 'bar', 'self': 'http://example.com/1'},
            encoder=1)
        mock_priv.assert_called_once_with(request=request)
        wrapper.assert_called_once_with(
            result={'self': 'http://example.com/1', 'foo': 'bar', 'zoo': 1})

    @patch.object(jsonex, 'apply_privacy')
    @patch.object(jsonex, 'create_json_response')
    def test_jhttpcreated_auth_disabled(self, mock_create, mock_priv):
        request = Mock()
        request.registry._root_resources = {'foo': Mock(auth=False)}
        resp = jsonex.JHTTPCreated(
            resource={'foo': 'bar', 'zoo': 1},
            location='http://example.com/1',
            encoder=1,
            request=request)
        mock_create.assert_called_once_with(
            resp, data={'foo': 'bar', 'zoo': 1, 'self': 'http://example.com/1'},
            encoder=1)
        assert not mock_priv.called
