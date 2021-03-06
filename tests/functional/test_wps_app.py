"""
Based on tests from:

* https://github.com/geopython/pywps/tree/master/tests
* https://github.com/mmerickel/pyramid_services/tree/master/pyramid_services/tests
* http://webtest.pythonpaste.org/en/latest/
* http://docs.pylonsproject.org/projects/pyramid/en/latest/narr/testing.html
"""
import contextlib
import unittest

import pyramid.testing
import pytest
import xmltodict
from lxml import etree

from tests.utils import (
    get_test_weaver_app,
    get_test_weaver_config,
    mocked_execute_process,
    setup_config_with_celery,
    setup_config_with_mongodb,
    setup_config_with_pywps,
    setup_mongodb_processstore
)
from weaver.formats import CONTENT_TYPE_ANY_XML, CONTENT_TYPE_APP_XML
from weaver.processes.wps_default import HelloWPS
from weaver.processes.wps_testing import WpsTestProcess
from weaver.utils import str2bytes
from weaver.visibility import VISIBILITY_PRIVATE, VISIBILITY_PUBLIC


@pytest.mark.functional
class WpsAppTest(unittest.TestCase):
    def setUp(self):
        self.wps_path = "/ows/wps"
        settings = {
            "weaver.url": "",
            "weaver.wps": True,
            "weaver.wps_path": self.wps_path,
            "weaver.wps_metadata_identification_title": "Weaver WPS Test Server",
            "weaver.wps_metadata_provider_name": WpsAppTest.__name__
        }
        config = get_test_weaver_config(settings=settings)
        config = setup_config_with_mongodb(config)
        config = setup_config_with_pywps(config)
        config = setup_config_with_celery(config)
        self.process_store = setup_mongodb_processstore(config)
        self.app = get_test_weaver_app(config=config, settings=settings)

        # add processes by database Process type
        self.process_public = WpsTestProcess(identifier="process_public")
        self.process_private = WpsTestProcess(identifier="process_private")
        self.process_store.save_process(self.process_public)
        self.process_store.save_process(self.process_private)
        self.process_store.set_visibility(self.process_public.identifier, VISIBILITY_PUBLIC)
        self.process_store.set_visibility(self.process_private.identifier, VISIBILITY_PRIVATE)

        # add processes by pywps Process type
        self.process_store.save_process(HelloWPS())
        self.process_store.set_visibility(HelloWPS.identifier, VISIBILITY_PUBLIC)

    def tearDown(self):
        pyramid.testing.tearDown()

    def make_url(self, params):
        return "{}?{}".format(self.wps_path, params)

    def test_getcaps(self):
        resp = self.app.get(self.make_url("service=wps&request=getcapabilities"))
        assert resp.status_code == 200
        assert resp.content_type in CONTENT_TYPE_ANY_XML
        resp.mustcontain("</wps:Capabilities>")

    def test_getcaps_metadata(self):
        resp = self.app.get(self.make_url("service=wps&request=getcapabilities"))
        assert resp.status_code == 200
        assert resp.content_type in CONTENT_TYPE_ANY_XML
        xml_dict = xmltodict.parse(resp.text)
        assert xml_dict["wps:Capabilities"]["ows:ServiceIdentification"]["ows:Title"] == "Weaver WPS Test Server"
        assert xml_dict["wps:Capabilities"]["ows:ServiceProvider"]["ows:ProviderName"] == WpsAppTest.__name__

    def test_getcaps_filtered_processes_by_visibility(self):
        resp = self.app.get(self.make_url("service=wps&request=getcapabilities"))
        assert resp.status_code == 200
        assert resp.content_type in CONTENT_TYPE_ANY_XML
        resp.mustcontain("<wps:ProcessOfferings>")
        root = etree.fromstring(str2bytes(resp.text))  # test response has no 'content'
        process_offerings = list(filter(lambda e: "ProcessOfferings" in e.tag, root.iter(etree.Element)))
        assert len(process_offerings) == 1
        processes = [p for p in process_offerings[0]]
        ids = [pi.text for pi in [list(filter(lambda e: e.tag.endswith("Identifier"), p))[0] for p in processes]]
        assert self.process_private.identifier not in ids
        assert self.process_public.identifier in ids

    def test_describeprocess(self):
        template = "service=wps&request=describeprocess&version=1.0.0&identifier={}"
        params = template.format(HelloWPS.identifier)
        resp = self.app.get(self.make_url(params))
        assert resp.status_code == 200
        assert resp.content_type in CONTENT_TYPE_ANY_XML
        resp.mustcontain("</wps:ProcessDescriptions>")

    def test_describeprocess_filtered_processes_by_visibility(self):
        param_template = "service=wps&request=describeprocess&version=1.0.0&identifier={}"

        url = self.make_url(param_template.format(self.process_public.identifier))
        resp = self.app.get(url)
        assert resp.status_code == 200
        assert resp.content_type in CONTENT_TYPE_ANY_XML
        resp.mustcontain("</wps:ProcessDescriptions>")

        url = self.make_url(param_template.format(self.process_private.identifier))
        resp = self.app.get(url, expect_errors=True)
        assert resp.status_code == 400
        assert resp.content_type in CONTENT_TYPE_ANY_XML
        resp.mustcontain("<ows:ExceptionText>Unknown process")

    def test_execute_allowed_demo(self):
        template = "service=wps&request=execute&version=1.0.0&identifier={}&datainputs=name=tux"
        params = template.format(HelloWPS.identifier)
        url = self.make_url(params)
        with contextlib.ExitStack() as stack_exec:
            for mock_exec in mocked_execute_process():
                stack_exec.enter_context(mock_exec)
            resp = self.app.get(url)
        assert resp.status_code == 200  # FIXME: replace by 202 Accepted (?) https://github.com/crim-ca/weaver/issues/14
        assert resp.content_type in CONTENT_TYPE_ANY_XML
        resp.mustcontain("<wps:ExecuteResponse")
        resp.mustcontain("<wps:ProcessAccepted")
        resp.mustcontain("PyWPS Process {}".format(HelloWPS.identifier))

    def test_execute_deployed_with_visibility_allowed(self):
        headers = {"Accept": CONTENT_TYPE_APP_XML}
        params_template = "service=wps&request=execute&version=1.0.0&identifier={}&datainputs=test_input=test"
        url = self.make_url(params_template.format(self.process_public.identifier))
        with contextlib.ExitStack() as stack_exec:
            for mock_exec in mocked_execute_process():
                stack_exec.enter_context(mock_exec)
            resp = self.app.get(url, headers=headers)
        assert resp.status_code == 200  # FIXME: replace by 202 Accepted (?) https://github.com/crim-ca/weaver/issues/14
        assert resp.content_type in CONTENT_TYPE_ANY_XML
        resp.mustcontain("<wps:ExecuteResponse")
        resp.mustcontain("<wps:ProcessAccepted")
        resp.mustcontain("PyWPS Process {}".format(self.process_public.identifier))

    def test_execute_deployed_with_visibility_denied(self):
        headers = {"Accept": CONTENT_TYPE_APP_XML}
        params_template = "service=wps&request=execute&version=1.0.0&identifier={}&datainputs=test_input=test"
        url = self.make_url(params_template.format(self.process_private.identifier))
        with contextlib.ExitStack() as stack_exec:
            for mock_exec in mocked_execute_process():
                stack_exec.enter_context(mock_exec)
            resp = self.app.get(url, headers=headers, expect_errors=True)
        assert resp.status_code == 403
        assert resp.content_type in CONTENT_TYPE_ANY_XML, "Error Response: {}".format(resp.text)
        resp.mustcontain("<Exception exceptionCode=\"AccessForbidden\" locator=\"service\">")
        err_desc = "Process with ID '{}' is not accessible.".format(self.process_private.identifier)
        resp.mustcontain("<ExceptionText>{}</ExceptionText>".format(err_desc))
