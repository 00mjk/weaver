"""
Unit tests of functions within :mod:`weaver.processes.wps_package`.

.. seealso::
    - :mod:`tests.functional.wps_package`.
"""
import tempfile
from collections import OrderedDict
from copy import deepcopy

from pytest import fail
from pywps.app import WPSRequest

from weaver.datatype import Process
from weaver.processes.wps_package import _get_package_ordered_io  # noqa: W0212
from weaver.processes.wps_package import WpsPackage


def test_get_package_ordered_io_with_builtin_dict_and_hints():
    """
    Validate that I/O are all still there in the results with their respective contents.

    Literal types should be modified to a dictionary with ``type`` key.
    All dictionary contents should then remain as is, except with added ``id``.

    .. note::
        Ordering is not mandatory, so we don't validate this.
        Also actually hard to test since employed python version running the test changes the behaviour.
    """
    test_inputs = {
        "id-literal-type": "float",
        "id-dict-details": {
            "type": "string"
        },
        "id-array-type": {
            "type": {
                "type": "array",
                "items": "float"
            }
        },
        "id-literal-array": "string[]"
    }
    test_wps_hints = [
        {"id": "id-literal-type"},
        {"id": "id-array-type"},
        {"id": "id-dict-with-more-stuff"},
        {"id": "id-dict-details"},
    ]
    expected_result = [
        {"id": "id-literal-type", "type": "float"},
        {"id": "id-dict-details", "type": "string"},
        {"id": "id-array-type", "type": {"type": "array", "items": "float"}},
        {"id": "id-literal-array", "type": "string[]"}
    ]
    result = _get_package_ordered_io(test_inputs, test_wps_hints)
    assert isinstance(result, list) and len(result) == len(expected_result)
    # *maybe* not same order, so validate values accordingly
    for expect in expected_result:
        validated = False
        for res in result:
            if res["id"] == expect["id"]:
                assert res == expect
                validated = True
        if not validated:
            raise AssertionError("expected '{}' was not validated against any result value".format(expect["id"]))


def test_get_package_ordered_io_with_ordered_dict():
    test_inputs = OrderedDict([
        ("id-literal-type", "float"),
        ("id-dict-details", {"type": "string"}),
        ("id-array-type", {
            "type": {
                "type": "array",
                "items": "float"
            }
        }),
        ("id-literal-array", "string[]"),
    ])
    expected_result = [
        {"id": "id-literal-type", "type": "float"},
        {"id": "id-dict-details", "type": "string"},
        {"id": "id-array-type", "type": {"type": "array", "items": "float"}},
        {"id": "id-literal-array", "type": "string[]"}
    ]
    result = _get_package_ordered_io(test_inputs)
    assert isinstance(result, list) and len(result) == len(expected_result)
    assert result == expected_result


def test_get_package_ordered_io_with_list():
    """
    Everything should remain the same as list variant is only allowed to have I/O objects.
    (i.e.: not allowed to have both objects and literal string-type simultaneously as for dictionary variant).
    """
    expected_result = [
        {"id": "id-literal-type", "type": "float"},
        {"id": "id-dict-details", "type": "string"},
        {"id": "id-array-type", "type": {"type": "array", "items": "float"}},
        {"id": "id-literal-array", "type": "string[]"}
    ]
    result = _get_package_ordered_io(deepcopy(expected_result))
    assert isinstance(result, list) and len(result) == len(expected_result)
    assert result == expected_result


def test_stdout_stderr_logging_for_commandline_tool_success():
    """
    Execute a process and assert that stdout is correctly logged to log file.
    """
    process = Process({
        "title": "test-stdout-stderr",
        "id": "test-stdout-stderr",
        "package": {
            "cwlVersion": "v1.0",
            "class": "CommandLineTool",
            "baseCommand": "echo",
            "inputs": {
                "message": {
                    "type": "string",
                    "inputBinding": {
                        "position": 1
                    }
                }
            },
            "outputs": {

            }
        }
    })

    payload = process
    package = process["package"]
    title = process["title"]
    identifier = process["id"]

    # WPSPackage._handle()
    log_file = tempfile.NamedTemporaryFile()
    status_location = log_file.name
    workdir = tempfile.TemporaryDirectory()

    class TestWpsPackage(WpsPackage):
        @property
        def status_location(self):
            return status_location

    wps_package_instance = TestWpsPackage(identifier=identifier, title=title, payload=payload, package=package)
    wps_package_instance.set_workdir(workdir.name)

    # WPSRequest mock
    wps_request = WPSRequest()
    wps_request.json = {
        "identifier": "test-stdout-stderr",
        "operation": "execute",
        "version": "1.0.0",
        "language": "null",
        "identifiers": "null",
        "store_execute": "true",
        "status": "true",
        "lineage": "true",
        "raw": "false",
        "inputs": {
            "message": [
                 {
                    "identifier": "message",
                    "title": "A dummy message",
                    "type": "literal",
                    "data_type": "string",
                    "data": "Dummy message",
                    "allowed_values": [

                    ],
                 }
            ]
        },
        "outputs": {

        }
    }

    # ExecuteResponse mock
    wps_response = type("", (object,), {"_update_status": lambda *_, **__: 1})()

    wps_package_instance._handler(wps_request, wps_response)

    # log assertions
    with open(status_location + ".log", "r") as file:
        log_data = file.read()
        assert "Dummy message" in log_data


def test_stdout_stderr_logging_for_commandline_tool_failure():
    """
    Execute a process and assert that stderr is correctly logged to log file.
    """
    process = Process({
        "title": "test-stdout-stderr",
        "id": "test-stdout-stderr",
        "package": {
            "cwlVersion": "v1.0",
            "class": "CommandLineTool",
            "baseCommand": "not_existing_command",
            "inputs": {
                "message": {
                    "type": "string",
                    "inputBinding": {
                        "position": 1
                    }
                }
            },
            "outputs": {

            }
        }
    })

    payload = process
    package = process["package"]
    title = process["title"]
    identifier = process["id"]

    # WPSPackage._handle()
    log_file = tempfile.NamedTemporaryFile()
    status_location = log_file.name
    workdir = tempfile.TemporaryDirectory()

    class TestWpsPackage(WpsPackage):
        @property
        def status_location(self):
            return status_location

    wps_package_instance = TestWpsPackage(identifier=identifier, title=title, payload=payload, package=package)
    wps_package_instance.set_workdir(workdir.name)

    # WPSRequest mock
    wps_request = WPSRequest()
    wps_request.json = {
        "identifier": "test-stdout-stderr",
        "operation": "execute",
        "version": "1.0.0",
        "language": "null",
        "identifiers": "null",
        "store_execute": "true",
        "status": "true",
        "lineage": "true",
        "raw": "false",
        "inputs": {
            "message": [
                 {
                    "identifier": "message",
                    "title": "A dummy message",
                    "type": "literal",
                    "data_type": "string",
                    "data": "Dummy message",
                    "allowed_values": [

                    ],
                 }
            ]
        },
        "outputs": {

        }
    }

    # ExecuteResponse mock
    wps_response = type("", (object,), {"_update_status": lambda *_, **__: 1})()

    from weaver.exceptions import PackageExecutionError

    try:
        wps_package_instance._handler(wps_request, wps_response)
    except PackageExecutionError as exception:
        assert "Completed permanentFail" in exception.args[0]
    else:
        fail("\"wps_package._handler()\" was expected to throw \"PackageExecutionError\" exception")
