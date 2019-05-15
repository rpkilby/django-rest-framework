import copy

from django.test import TestCase
from django.urls import path
from django.views import generic

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.settings import APISettings, api_settings
from rest_framework.test import APIRequestFactory, URLPatternsTestCase, override_settings
from rest_framework.views import APIView

factory = APIRequestFactory()

JSON_ERROR = 'JSON parse error - Expecting value:'


class BasicView(APIView):
    def get(self, request, *args, **kwargs):
        return Response({'method': 'GET'})

    def post(self, request, *args, **kwargs):
        return Response({'method': 'POST', 'data': request.data})


@api_view(['GET', 'POST', 'PUT', 'PATCH'])
def basic_view(request):
    if request.method == 'GET':
        return {'method': 'GET'}
    elif request.method == 'POST':
        return {'method': 'POST', 'data': request.data}
    elif request.method == 'PUT':
        return {'method': 'PUT', 'data': request.data}
    elif request.method == 'PATCH':
        return {'method': 'PATCH', 'data': request.data}


class ErrorView(APIView):
    def get(self, request, *args, **kwargs):
        raise Exception


def custom_handler(exc, context):
    if isinstance(exc, SyntaxError):
        return Response({'error': 'SyntaxError'}, status=400)
    return Response({'error': 'UnknownError'}, status=500)


class OverridenSettingsView(APIView):
    settings = APISettings({'EXCEPTION_HANDLER': custom_handler})

    def get(self, request, *args, **kwargs):
        raise SyntaxError('request is invalid syntax')


@api_view(['GET'])
def error_view(request):
    raise Exception


def sanitise_json_error(error_dict):
    """
    Exact contents of JSON error messages depend on the installed version
    of json.
    """
    ret = copy.copy(error_dict)
    chop = len(JSON_ERROR)
    ret['detail'] = ret['detail'][:chop]
    return ret


class ClassBasedViewIntegrationTests(TestCase):
    def setUp(self):
        self.view = BasicView.as_view()

    def test_400_parse_error(self):
        request = factory.post('/', 'f00bar', content_type='application/json')
        response = self.view(request)
        expected = {
            'detail': JSON_ERROR
        }
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert sanitise_json_error(response.data) == expected


class FunctionBasedViewIntegrationTests(TestCase):
    def setUp(self):
        self.view = basic_view

    def test_400_parse_error(self):
        request = factory.post('/', 'f00bar', content_type='application/json')
        response = self.view(request)
        expected = {
            'detail': JSON_ERROR
        }
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert sanitise_json_error(response.data) == expected


# Disable exception propagation since it preempts request logging
@override_settings(DEBUG_PROPAGATE_EXCEPTIONS=False)
class TestExceptionLogging(URLPatternsTestCase, TestCase):

    class DjangoExceptionView(generic.View):
        def get(self, request, *args, **kwargs):
            raise APIException('django exception')

    class DRFExceptionView(APIView):
        def get(self, request, *args, **kwargs):
            raise APIException('drf exception')

    urlpatterns = [
        path('django', DjangoExceptionView.as_view()),
        path('drf', DRFExceptionView.as_view()),
    ]

    def test_django_exception_logging(self):
        with self.assertLogs('django.request', 'ERROR') as cm:
            # Django's test client raises sys.exc_info, even though the WSGI
            # handler has caught and returned an appropriate error response.
            with self.assertRaisesMessage(APIException, 'django exception'):
                self.client.get('/django')

            assert len(cm.records) == 1
            record = cm.records[0]

        assert record.getMessage() == 'Internal Server Error: /django'
        assert record.exc_info is not None
        assert record.exc_info[0] is APIException
        assert str(record.exc_info[1]) == 'django exception'

    def test_drf_exception_logging(self):
        with self.assertLogs('django.request', 'ERROR') as cm:
            # DRF handles exceptions internally in the view layer, preempting
            # the WSGI handler's uncaught exception handling and in turn,
            # preventing the test client from reraising the exception.
            self.client.get('/drf')

            assert len(cm.records) == 1
            record = cm.records[0]

        assert record.getMessage() == 'Internal Server Error: /drf'
        assert record.exc_info is not None
        assert record.exc_info[0] is APIException
        assert str(record.exc_info[1]) == 'drf exception'


class TestCustomExceptionHandler(TestCase):
    def setUp(self):
        self.DEFAULT_HANDLER = api_settings.EXCEPTION_HANDLER

        def exception_handler(exc, request):
            return Response('Error!', status=status.HTTP_400_BAD_REQUEST)

        api_settings.EXCEPTION_HANDLER = exception_handler

    def tearDown(self):
        api_settings.EXCEPTION_HANDLER = self.DEFAULT_HANDLER

    def test_class_based_view_exception_handler(self):
        view = ErrorView.as_view()

        request = factory.get('/', content_type='application/json')
        response = view(request)
        expected = 'Error!'
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == expected

    def test_function_based_view_exception_handler(self):
        view = error_view

        request = factory.get('/', content_type='application/json')
        response = view(request)
        expected = 'Error!'
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data == expected


class TestCustomSettings(TestCase):
    def setUp(self):
        self.view = OverridenSettingsView.as_view()

    def test_get_exception_handler(self):
        request = factory.get('/', content_type='application/json')
        response = self.view(request)
        assert response.status_code == 400
        assert response.data == {'error': 'SyntaxError'}
