from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import os
    import typing
    from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
    if hasattr(typing, "TypedDict"):
        from typing import TypedDict  # pylint: disable=E0611,no-name-in-module
    else:
        from typing_extensions import TypedDict
    if hasattr(os, "PathLike"):
        FileSystemPathType = Union[os.PathLike, str]
    else:
        FileSystemPathType = str

    from celery.app import Celery
    from lxml.etree import _Element as XML  # noqa: W0212  # make available for use elsewhere
    from pyramid.registry import Registry
    from pyramid.request import Request as PyramidRequest
    from pyramid.response import Response as PyramidResponse
    from pyramid.testing import DummyRequest
    from pyramid.config import Configurator
    from pywps.app import WPSRequest
    from pywps import Process as ProcessWPS
    from requests import Request as RequestsRequest
    from requests.structures import CaseInsensitiveDict
    from webob.headers import ResponseHeaders, EnvironHeaders
    from webob.response import Response as WebobResponse
    from webtest.response import TestResponse
    from werkzeug.wrappers import Request as WerkzeugRequest

    # pylint: disable=W0611,unused-import,C0103,invalid-name
    from weaver.processes.wps_process_base import WpsProcessInterface
    from weaver.datatype import Process
    from weaver.status import AnyStatusType

    Number = Union[int, float]
    ValueType = Union[str, Number, bool]
    AnyValue = Optional[ValueType]
    AnyKey = Union[str, int]
    JsonList = List["JSON"]
    JsonObject = Dict[str, "JSON"]
    JSON = Union[AnyValue, JsonObject, JsonList]
    CWL = TypedDict("CWL", {"cwlVersion": str, "class": str, "inputs": JSON, "outputs": JSON})

    AnyContainer = Union[Configurator, Registry, PyramidRequest, Celery]
    SettingValue = Optional[JSON]
    SettingsType = Dict[str, SettingValue]
    AnySettingsContainer = Union[AnyContainer, SettingsType]
    AnyRegistryContainer = AnyContainer
    AnyDatabaseContainer = AnyContainer

    CookiesType = Dict[str, str]
    HeadersType = Dict[str, str]
    CookiesTupleType = List[Tuple[str, str]]
    HeadersTupleType = List[Tuple[str, str]]
    CookiesBaseType = Union[CookiesType, CookiesTupleType]
    HeadersBaseType = Union[HeadersType, HeadersTupleType]
    HeaderCookiesType = Union[HeadersBaseType, CookiesBaseType]
    HeaderCookiesTuple = Union[Tuple[None, None], Tuple[HeadersBaseType, CookiesBaseType]]
    AnyHeadersContainer = Union[HeadersBaseType, ResponseHeaders, EnvironHeaders, CaseInsensitiveDict]
    AnyCookiesContainer = Union[CookiesBaseType, WPSRequest, PyramidRequest, AnyHeadersContainer]
    AnyResponseType = Union[PyramidResponse, WebobResponse, TestResponse]
    AnyRequestType = Union[PyramidRequest, WerkzeugRequest, RequestsRequest, DummyRequest]

    AnyProcess = Union[Process, ProcessWPS]
    AnyProcessType = Union[Type[Process], Type[ProcessWPS]]

    GlobType = TypedDict("GlobType", {"glob": str})
    ExpectedOutputType = TypedDict("ExpectedOutputType", {"type": str, "id": str, "outputBinding": GlobType})
    GetJobProcessDefinitionFunction = Callable[[str, Dict[str, str], Dict[str, Any]], WpsProcessInterface]
    ToolPathObjectType = Dict[str, Any]

    # update_status(provider, message, progress, status)
    UpdateStatusPartialFunction = Callable[[str, str, int, AnyStatusType], None]
