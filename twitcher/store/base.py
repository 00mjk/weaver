"""
Store adapters to persist and retrieve data during the twitcher process or
for later use. For example an access token storage and a service registry.

This module provides base classes that can be extended to implement your own
solution specific to your needs.

The implementation is based on `python-oauth2 <http://python-oauth2.readthedocs.io/en/latest/>`_.
"""


class AccessTokenStore(object):

    def save_token(self, access_token):
        """
        Stores an access token with additional data.
        """
        raise NotImplementedError

    def delete_token(self, token):
        """
        Deletes an access token from the store using its token string to identify it.
        This invalidates both the access token and the token.

        :param token: A string containing the token.
        :return: None.
        """
        raise NotImplementedError

    def fetch_by_token(self, token):
        """
        Fetches an access token from the store using its token string to
        identify it.

        :param token: A string containing the token.
        :return: An instance of :class:`twitcher.datatype.AccessToken`.
        """
        raise NotImplementedError

    def clean_tokens(self):
        """
        Removes all tokens from database.
        """
        raise NotImplementedError


class ServiceRegistryStore(object):
    """
    Registry storage for OWS services.
    """

    def register_service(self, url, name=None, service_type='wps', public=False, c4i=False, overwrite=True):
        """
        Adds OWS service with given name to registry database.
        """
        raise NotImplementedError

    def unregister_service(self, name):
        """
        Removes service from registry database.
        """
        raise NotImplementedError

    def list_services(self):
        """
        Lists all services in registry database.
        """
        raise NotImplementedError

    def get_service_by_name(self, name):
        """
        Get service for given ``name`` from registry database.
        """
        raise NotImplementedError

    def get_service_by_url(self, url):
        """
        Get service for given ``url`` from registry database.
        """
        raise NotImplementedError

    def get_service_name(self, url):
        raise NotImplementedError

    def is_public(self, name):
        raise NotImplementedError

    def clear_services(self):
        """
        Removes all OWS services from registry database.
        """
        raise NotImplementedError