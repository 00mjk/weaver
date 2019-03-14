"""
Stores to read/write data to from/to mongodb using pymongo.
"""

from weaver.datatype import Service, Process, Job, Quote, Bill
from weaver.store.base import StoreServices, StoreProcesses, StoreJobs, StoreQuotes, StoreBills
from weaver.exceptions import (
    ServiceRegistrationError, ServiceNotFound, ServiceNotAccessible,
    ProcessRegistrationError, ProcessNotFound, ProcessNotAccessible, ProcessInstanceError,
    JobRegistrationError, JobNotFound, JobUpdateError,
    QuoteRegistrationError, QuoteNotFound, QuoteInstanceError,
    BillRegistrationError, BillNotFound, BillInstanceError,
)
from weaver.utils import get_base_url, islambda, now, get_sane_name
from weaver.execute import EXECUTE_MODE_ASYNC, EXECUTE_MODE_SYNC
from weaver.processes.types import PROCESS_WORKFLOW, PROCESS_APPLICATION, PROCESS_WPS
from weaver.status import STATUS_ACCEPTED, map_status, job_status_categories
from weaver.visibility import visibility_values, VISIBILITY_PRIVATE, VISIBILITY_PUBLIC
from weaver.sort import (
    job_sort_values,
    quote_sort_values,
    bill_sort_values,
    SORT_ID,
    SORT_USER,
    SORT_CREATED,
    SORT_FINISHED,
)
# noinspection PyPackageRequirements
from pywps import Process as ProcessWPS
from typing import TYPE_CHECKING
from pyramid.request import Request
from pymongo import ASCENDING, DESCENDING
import pymongo
import six
import logging
if TYPE_CHECKING:
    from pymongo.collection import Collection
    from typing import Any, AnyStr, Dict, List, Optional, Tuple, Union

LOGGER = logging.getLogger(__name__)


class MongodbStore(object):
    """
    Base class extended by all concrete store implementations.
    """

    def __init__(self, collection, sane_name_config=None):
        # type: (Collection, Optional[Dict[AnyStr, Any]]) -> None
        if not isinstance(collection, pymongo.collection.Collection):
            raise TypeError("Collection not of expected type.")
        self.collection = collection  # type: Collection
        self.sane_name_config = sane_name_config or {}

    @classmethod
    def get_args_kwargs(cls, *args, **kwargs):
        # type: (Any, Any) -> Tuple[Tuple, Dict]
        """
        Filters :class:`MongodbStore`-specific arguments to safely pass them down its ``__init__``.
        """
        collection = None
        if len(args):
            collection = args[0]
        elif "collection" in kwargs:
            collection = kwargs["collection"]
        sane_name_config = kwargs.get("sane_name_config", None)
        return tuple([collection]), {"sane_name_config": sane_name_config}


# noinspection PyUnusedLocal
class MongodbServiceStore(StoreServices, MongodbStore):
    """
    Registry for OWS services. Uses mongodb to store service url and attributes.
    """

    def __init__(self, *args, **kwargs):
        db_args, db_kwargs = MongodbStore.get_args_kwargs(*args, **kwargs)
        StoreServices.__init__(self)
        MongodbStore.__init__(self, *db_args, **db_kwargs)

    def save_service(self, service, overwrite=True, request=None):
        # type: (Service, Optional[bool], Optional[Request]) -> Service
        """
        Stores an OWS service in mongodb.
        """
        service_url = get_base_url(service.url)
        # check if service is already registered
        if self.collection.count_documents({"url": service_url}) > 0:
            if overwrite:
                self.collection.delete_one({"url": service_url})
            else:
                raise ServiceRegistrationError("service url already registered.")
        service_name = get_sane_name(service.name, **self.sane_name_config)
        if self.collection.count_documents({"name": service_name}) > 0:
            if overwrite:
                self.collection.delete_one({"name": service_name})
            else:
                raise ServiceRegistrationError("service name already registered.")
        self.collection.insert_one(Service(
            url=service_url,
            name=service_name,
            type=service.type,
            public=service.public,
            auth=service.auth))
        return self.fetch_by_url(url=service_url, request=request)

    def delete_service(self, name, request=None):
        # type: (AnyStr, Optional[Request]) -> bool
        """
        Removes service from mongodb storage.
        """
        self.collection.delete_one({"name": name})
        return True

    def list_services(self, request=None):
        # type: (Optional[Request]) -> List[Service]
        """
        Lists all services in mongodb storage.
        """
        my_services = []
        for service in self.collection.find().sort("name", pymongo.ASCENDING):
            my_services.append(Service(service))
        return my_services

    def fetch_by_name(self, name, visibility=None, request=None):
        # type: (AnyStr, Optional[AnyStr], Optional[Request]) -> Service
        """
        Gets service for given ``name`` from mongodb storage.
        """
        service = self.collection.find_one({"name": name})
        if not service:
            raise ServiceNotFound("Service '{}' could not be found.".format(name))
        service = Service(service)
        same_visibility = (service.public and visibility == VISIBILITY_PUBLIC) or \
                          (not service.public and visibility == VISIBILITY_PRIVATE)
        if visibility is not None and not same_visibility:
            raise ServiceNotAccessible("Service '{}' cannot be accessed.".format(name))
        return service

    def fetch_by_url(self, url, request=None):
        # type: (AnyStr, Optional[Request]) -> Service
        """
        Gets service for given ``url`` from mongodb storage.
        """
        service = self.collection.find_one({"url": get_base_url(url)})
        if not service:
            raise ServiceNotFound
        return Service(service)

    def clear_services(self, request=None):
        # type: (Optional[Request]) -> bool
        """
        Removes all OWS services from mongodb storage.
        """
        self.collection.drop()
        return True


# noinspection PyUnusedLocal
class MongodbProcessStore(StoreProcesses, MongodbStore):
    """
    Registry for processes. Uses mongodb to store processes and attributes.
    """
    def __init__(self, *args, **kwargs):
        db_args, db_kwargs = MongodbStore.get_args_kwargs(*args, **kwargs)
        StoreProcesses.__init__(self)
        MongodbStore.__init__(self, *db_args, **db_kwargs)
        registry = kwargs.get("registry")
        settings = kwargs.get("settings", {}) if not registry else registry.settings
        default_processes = kwargs.get("default_processes")
        self.default_host = settings.get("weaver.url", "")
        self.default_wps_endpoint = "{host}{wps}".format(host=self.default_host,
                                                         wps=settings.get("weaver.wps_path", ""))
        if default_processes:
            registered_processes = [process.identifier for process in self.list_processes()]
            for process in default_processes:
                process_name = self._get_process_id(process)
                if process_name not in registered_processes:
                    self._add_process(process)

    def _add_process(self, process):
        if isinstance(process, ProcessWPS):
            new_process = Process.from_wps(process, processEndpointWPS1=self.default_wps_endpoint)
        else:
            new_process = process
        if not isinstance(new_process, Process):
            raise ProcessInstanceError("Unsupported process type '{}'".format(type(process)))

        # apply defaults if not specified
        new_process["type"] = self._get_process_type(process)
        new_process["identifier"] = self._get_process_id(process)
        new_process["processEndpointWPS1"] = self._get_process_endpoint_wps1(process)
        new_process["visibility"] = new_process.visibility
        self.collection.insert_one(new_process)

    @staticmethod
    def _get_process_field(process, function_dict):
        """
        Takes a lambda expression or a dict of process-specific lambda expressions to retrieve a field.
        Validates that the passed process object is one of the supported types.

        :param process: process to retrieve the field from.
        :param function_dict: lambda or dict of lambda of process type
        :return: retrieved field if the type was supported
        :raises: ProcessInstanceError on invalid process type
        """
        if isinstance(process, Process):
            if islambda(function_dict):
                return function_dict()
            return function_dict[Process]()
        elif isinstance(process, ProcessWPS):
            if islambda(function_dict):
                return function_dict()
            return function_dict[ProcessWPS]()
        else:
            raise ProcessInstanceError("Unsupported process type '{}'".format(type(process)))

    def _get_process_id(self, process):
        return self._get_process_field(process, lambda: process.identifier)

    def _get_process_type(self, process):
        return self._get_process_field(process, {Process: lambda: process.type,
                                                 ProcessWPS: lambda: getattr(process, "type", PROCESS_WPS)}).lower()

    def _get_process_endpoint_wps1(self, process):
        url = self._get_process_field(process, {Process: lambda: process.processEndpointWPS1,
                                                ProcessWPS: lambda: None})
        if not url:
            url = self.default_wps_endpoint
        return url

    def save_process(self, process, overwrite=True, request=None):
        # type: (Union[Process, ProcessWPS], Optional[bool], Optional[Request]) -> Process
        """
        Stores a process in storage.

        :param process: An instance of :class:`weaver.datatype.Process`.
        :param overwrite: Overwrite the matching process instance by name if conflicting.
        :param request: <unused>
        """
        process_id = self._get_process_id(process)
        sane_name = get_sane_name(process_id, **self.sane_name_config)
        if self.collection.count_documents({"identifier": sane_name}) > 0:
            if overwrite:
                self.collection.delete_one({"identifier": sane_name})
            else:
                raise ProcessRegistrationError("Process '{}' already registered.".format(sane_name))
        process.identifier = sane_name  # must use property getter/setter to match both 'Process' types
        self._add_process(process)
        return self.fetch_by_id(sane_name)

    def delete_process(self, process_id, visibility=None, request=None):
        # type: (AnyStr, Optional[AnyStr], Optional[Request]) -> bool
        """
        Removes process from database, optionally filtered by visibility.
        If ``visibility=None``, the process is deleted (if existing) regardless of its visibility value.
        """
        sane_name = get_sane_name(process_id, **self.sane_name_config)
        process = self.fetch_by_id(sane_name, visibility=visibility, request=request)
        if not process:
            raise ProcessNotFound("Process '{}' could not be found.".format(sane_name))
        return bool(self.collection.delete_one({"identifier": sane_name}).deleted_count)

    def list_processes(self, visibility=None, request=None):
        # type: (Optional[AnyStr], Optional[Request]) -> List[Process]
        """
        Lists all processes in database, optionally filtered by `visibility`.

        :param visibility: One value amongst `weaver.visibility`.
        :param request:
        """
        db_processes = []
        search_filters = {}
        if visibility is None:
            visibility = visibility_values
        if isinstance(visibility, six.string_types):
            visibility = [visibility]
        for v in visibility:
            if v not in visibility_values:
                raise ValueError("Invalid visibility value '{0!s}' is not one of {1!s}"
                                 .format(v, list(visibility_values)))
        search_filters["visibility"] = {"$in": list(visibility)}
        for process in self.collection.find(search_filters).sort("identifier", pymongo.ASCENDING):
            db_processes.append(Process(process))
        return db_processes

    def fetch_by_id(self, process_id, visibility=None, request=None):
        # type: (AnyStr, Optional[AnyStr], Optional[Request]) -> Process
        """
        Get process for given `process_id` from storage, optionally filtered by `visibility`.
        If ``visibility=None``, the process is retrieved (if existing) regardless of its visibility value.

        :param process_id: process identifier
        :param visibility: one value amongst `weaver.visibility`.
        :param request:
        :return: An instance of :class:`weaver.datatype.Process`.
        """
        sane_name = get_sane_name(process_id, **self.sane_name_config)
        process = self.collection.find_one({"identifier": sane_name})
        if not process:
            raise ProcessNotFound("Process '{}' could not be found.".format(sane_name))
        process = Process(process)
        if visibility is not None and process.visibility != visibility:
            raise ProcessNotAccessible("Process '{}' cannot be accessed.".format(sane_name))
        return process

    def get_visibility(self, process_id, request=None):
        # type: (AnyStr, Optional[Request]) -> AnyStr
        """
        Get `visibility` of a process.

        :return: One value amongst `weaver.visibility`.
        """
        process = self.fetch_by_id(process_id)
        return process.visibility

    def set_visibility(self, process_id, visibility, request=None):
        # type: (AnyStr, AnyStr, Optional[Request]) -> None
        """
        Set `visibility` of a process.

        :param visibility: One value amongst `weaver.visibility`.
        :param process_id:
        :param request:
        :raises: ``TypeError`` or ``ValueError`` in case of invalid parameter.
        """
        process = self.fetch_by_id(process_id)
        process.visibility = visibility
        self.save_process(process, overwrite=True)

    def clear_processes(self, request=None):
        # type: (Optional[Request]) -> bool
        """
        Clears all processes from the store.
        """
        self.collection.drop()
        return True


# noinspection PyUnusedLocal
class MongodbJobStore(StoreJobs, MongodbStore):
    """
    Registry for process jobs tracking. Uses mongodb to store job attributes.
    """
    def __init__(self, *args, **kwargs):
        db_args, db_kwargs = MongodbStore.get_args_kwargs(*args, **kwargs)
        StoreJobs.__init__(self)
        MongodbStore.__init__(self, *db_args, **db_kwargs)

    def save_job(self,
                 task_id,               # type: AnyStr
                 process,               # type: AnyStr
                 service=None,          # type: Optional[AnyStr]
                 inputs=None,           # type: Optional[List[Any]]
                 is_workflow=False,     # type: Optional[bool]
                 user_id=None,          # type: Optional[int]
                 execute_async=True,    # type: Optional[bool]
                 custom_tags=None,      # type: Optional[List[AnyStr]]
                 access=None,           # type: Optional[AnyStr]
                 ):                     # type: (...) -> Job
        """
        Stores a job in mongodb.
        """
        try:
            tags = ["dev"]
            tags.extend(filter(lambda t: t, custom_tags or list()))
            if is_workflow:
                tags.append(PROCESS_WORKFLOW)
            else:
                tags.append(PROCESS_APPLICATION)
            if execute_async:
                tags.append(EXECUTE_MODE_ASYNC)
            else:
                tags.append(EXECUTE_MODE_SYNC)
            if not access:
                access = VISIBILITY_PRIVATE
            new_job = Job({
                "task_id": task_id,
                "user_id": user_id,
                "service": service,     # provider identifier (WPS service)
                "process": process,     # process identifier (WPS request)
                "inputs": inputs,
                "status": map_status(STATUS_ACCEPTED),
                "execute_async": execute_async,
                "is_workflow": is_workflow,
                "created": now(),
                "tags": tags,
                "access": access,
            })
            self.collection.insert_one(new_job)
            job = self.fetch_by_id(job_id=new_job.id)
        except Exception as ex:
            raise JobRegistrationError("Error occurred during job registration: [{}]".format(repr(ex)))
        if job is None:
            raise JobRegistrationError("Failed to retrieve registered job.")
        return job

    def update_job(self, job):
        # type: (Job) -> Job
        """
        Updates a job parameters in mongodb storage.
        :param job: instance of ``weaver.datatype.Job``.
        """
        try:
            result = self.collection.update_one({"id": job.id}, {"$set": job.params})
            if result.acknowledged and result.modified_count == 1:
                return self.fetch_by_id(job.id)
        except Exception as ex:
            raise JobUpdateError("Error occurred during job update: [{}]".format(repr(ex)))
        raise JobUpdateError("Failed to update specified job: '{}'".format(str(job)))

    def delete_job(self, job_id, request=None):
        # type: (AnyStr, Optional[Request]) -> bool
        """
        Removes job from mongodb storage.
        """
        self.collection.delete_one({"id": job_id})
        return True

    def fetch_by_id(self, job_id, request=None):
        # type: (AnyStr, Optional[Request]) -> Job
        """
        Gets job for given ``job_id`` from mongodb storage.
        """
        job = self.collection.find_one({"id": job_id})
        if not job:
            raise JobNotFound("Could not find job matching: '{}'".format(job_id))
        return Job(job)

    def list_jobs(self, request=None):
        # type: (Optional[Request]) -> List[Job]
        """
        Lists all jobs in mongodb storage.
        For user-specific access to available jobs, use :meth:`MongodbJobStore.find_jobs` instead.
        """
        jobs = []
        for job in self.collection.find().sort("id", ASCENDING):
            jobs.append(Job(job))
        return jobs

    def find_jobs(self,
                  request,          # type: Request
                  page=0,           # type: Optional[int]
                  limit=10,         # type: Optional[int]
                  process=None,     # type: Optional[AnyStr]
                  service=None,     # type: Optional[AnyStr]
                  tags=None,        # type: Optional[List[AnyStr]]
                  access=None,      # type: Optional[AnyStr]
                  status=None,      # type: Optional[AnyStr]
                  sort=None,        # type: Optional[AnyStr]
                  ):                # type: (...) -> Tuple[List[Job], int]
        """
        Finds all jobs in mongodb storage matching search filters.
        """

        if any(v in tags for v in visibility_values):
            raise ValueError("Visibility values not acceptable in 'tags', use 'access' instead.")

        search_filters = {}

        if request.has_permission("admin") and access in visibility_values:
            search_filters["access"] = access
        else:
            user_id = request.authenticated_userid
            if user_id is not None:
                search_filters["user_id"] = user_id
                if access in visibility_values:
                    search_filters["access"] = access
            else:
                search_filters["access"] = VISIBILITY_PUBLIC

        if tags:
            search_filters["tags"] = {"$all": tags}

        if status in job_status_categories.keys():
            search_filters["status"] = {"$in": job_status_categories[status]}
        elif status:
            search_filters["status"] = status

        if process is not None:
            search_filters["process"] = process

        if service is not None:
            search_filters["service"] = service

        if sort is None:
            sort = SORT_CREATED
        elif sort == SORT_USER:
            sort = "user_id"
        if sort not in job_sort_values:
            raise JobNotFound("Invalid sorting method: '{}'".format(repr(sort)))

        sort_order = DESCENDING if sort == SORT_FINISHED or sort == SORT_CREATED else ASCENDING
        sort_criteria = [(sort, sort_order)]
        found = self.collection.find(search_filters)
        count = self.collection.count_documents(search_filters)
        items = [Job(item) for item in list(found.skip(page * limit).limit(limit).sort(sort_criteria))]
        return items, count

    def clear_jobs(self, request=None):
        # type: (Optional[Request]) -> bool
        """
        Removes all jobs from mongodb storage.
        """
        self.collection.drop()
        return True


class MongodbQuoteStore(StoreQuotes, MongodbStore):
    """
    Registry for quotes. Uses mongodb to store quote attributes.
    """
    def __init__(self, *args, **kwargs):
        db_args, db_kwargs = MongodbStore.get_args_kwargs(*args, **kwargs)
        StoreQuotes.__init__(self)
        MongodbStore.__init__(self, *db_args, **db_kwargs)

    def save_quote(self, quote):
        # type: (Quote) -> Quote
        """
        Stores a quote in mongodb.
        """
        if not isinstance(quote, Quote):
            raise QuoteInstanceError("Invalid quote object: '{}'".format(repr(quote)))
        try:
            self.collection.insert_one(quote)
            quote = self.fetch_by_id(quote_id=quote.id)
        except Exception as ex:
            raise QuoteRegistrationError("Error occurred during quote registration: [{}]".format(repr(ex)))
        if quote is None:
            raise QuoteRegistrationError("Failed to retrieve registered quote.")
        return quote

    def fetch_by_id(self, quote_id):
        # type: (AnyStr) -> Quote
        """
        Gets quote for given ``quote_id`` from mongodb storage.
        """
        quote = self.collection.find_one({"id": quote_id})
        if not quote:
            raise QuoteNotFound("Could not find quote matching: '{}'".format(quote_id))
        return Quote(quote)

    def list_quotes(self):
        # type: (...) -> List[Quote]
        """
        Lists all quotes in mongodb storage.
        """
        quotes = []
        for quote in self.collection.find().sort("id", ASCENDING):
            quotes.append(Quote(quote))
        return quotes

    def find_quotes(self, process_id=None, page=0, limit=10, sort=None):
        # type: (Optional[AnyStr], Optional[int], Optional[int], Optional[AnyStr]) -> Tuple[List[Quote], int]
        """
        Finds all quotes in mongodb storage matching search filters.
        """
        search_filters = {}

        if isinstance(process_id, six.string_types):
            search_filters["process"] = process_id

        if sort is None:
            sort = SORT_ID
        if sort not in quote_sort_values:
            raise QuoteNotFound("Invalid sorting method: '{!s}'".format(sort))

        sort_order = ASCENDING
        sort_criteria = [(sort, sort_order)]
        found = self.collection.find(search_filters)
        count = found.count()
        items = [Quote(item) for item in list(found.skip(page * limit).limit(limit).sort(sort_criteria))]
        return items, count


class MongodbBillStore(StoreBills, MongodbStore):
    """
    Registry for bills. Uses mongodb to store bill attributes.
    """
    def __init__(self, *args, **kwargs):
        db_args, db_kwargs = MongodbStore.get_args_kwargs(*args, **kwargs)
        StoreBills.__init__(self)
        MongodbStore.__init__(self, *db_args, **db_kwargs)

    def save_bill(self, bill):
        # type: (Bill) -> Bill
        """
        Stores a bill in mongodb.
        """
        if not isinstance(bill, Bill):
            raise BillInstanceError("Invalid bill object: '{}'".format(repr(bill)))
        try:
            self.collection.insert_one(bill)
            bill = self.fetch_by_id(bill_id=bill.id)
        except Exception as ex:
            raise BillRegistrationError("Error occurred during bill registration: [{}]".format(repr(ex)))
        if bill is None:
            raise BillRegistrationError("Failed to retrieve registered bill.")
        return Bill(bill)

    def fetch_by_id(self, bill_id):
        # type: (AnyStr) -> Bill
        """
        Gets bill for given ``bill_id`` from mongodb storage.
        """
        bill = self.collection.find_one({"id": bill_id})
        if not bill:
            raise BillNotFound("Could not find bill matching: '{}'".format(bill_id))
        return Bill(bill)

    def list_bills(self):
        # type: (...) -> List[Bill]
        """
        Lists all bills in mongodb storage.
        """
        bills = []
        for bill in self.collection.find().sort("id", ASCENDING):
            bills.append(Bill(bill))
        return bills

    def find_bills(self, quote_id=None, page=0, limit=10, sort=None):
        # type: (Optional[AnyStr], Optional[int], Optional[int], Optional[AnyStr]) -> Tuple[List[Bill], int]
        """
        Finds all bills in mongodb storage matching search filters.
        """
        search_filters = {}

        if isinstance(quote_id, six.string_types):
            search_filters["quote"] = quote_id

        if sort is None:
            sort = SORT_ID
        if sort not in bill_sort_values:
            raise BillNotFound("Invalid sorting method: '{}'".format(repr(sort)))

        sort_order = ASCENDING
        sort_criteria = [(sort, sort_order)]
        found = self.collection.find(search_filters)
        count = found.count()
        items = [Bill(item) for item in list(found.skip(page * limit).limit(limit).sort(sort_criteria))]
        return items, count