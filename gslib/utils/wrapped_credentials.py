# -*- coding: utf-8 -*-
# Copyright 2022 Google LLC. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Classes and functions to allow google.auth credentials to be used within oauth2client.

In particular, the External Account credentials don't have an equivalent in
oauth2client, so we create helper methods to allow variants of this particular
class to be used in oauth2client workflows.
"""

import copy
import datetime
import io
import json

from google.auth import aws
from google.auth import credentials
from google.auth import exceptions
from google.auth import external_account
from google.auth import identity_pool
from google.auth.transport import requests
from gslib.utils import constants
import oauth2client

DEFAULT_SCOPES = [
    constants.Scopes.CLOUD_PLATFORM,
    constants.Scopes.CLOUD_PLATFORM_READ_ONLY,
    constants.Scopes.FULL_CONTROL,
    constants.Scopes.READ_ONLY,
    constants.Scopes.READ_WRITE,
]


class WrappedCredentials(oauth2client.client.OAuth2Credentials):
  """A utility class to use Google Auth credentials in place of oauth2client credentials.
  """
  NON_SERIALIZED_MEMBERS = frozenset(
      list(oauth2client.client.OAuth2Credentials.NON_SERIALIZED_MEMBERS) +
      ['_base'])

  def __init__(self, external_account_creds):
    """Initializes oauth2client credentials based on underlying Google Auth credentials.

    Args:
      external_account_creds: subclass of google.auth.external_account.Credentials
    """
    if not isinstance(external_account_creds, external_account.Credentials):
      raise TypeError("Invalid Credentials")
    self._base = external_account_creds
    super(WrappedCredentials, self).__init__(access_token=self._base.token,
                                             client_id=self._base._audience,
                                             client_secret=None,
                                             refresh_token=None,
                                             token_expiry=self._base.expiry,
                                             token_uri=None,
                                             user_agent=None)

  def _do_refresh_request(self, http):
    self._base.refresh(requests.Request())
    if self.store is not None:
      self.store.locked_put(self)

  @property
  def access_token(self):
    return self._base.token

  @access_token.setter
  def access_token(self, value):
    self._base.token = value

  @property
  def token_expiry(self):
    return self._base.expiry

  @token_expiry.setter
  def token_expiry(self, value):
    self._base.expiry = value

  def to_json(self):
    """Utility function that creates JSON repr. of a Credentials object.

    Returns:
        string, a JSON representation of this instance, suitable to pass to
        from_json().
    """

    serialized_data = super().to_json()
    deserialized_data = json.loads(serialized_data)
    deserialized_data['_base'] = copy.copy(self._base.info)
    deserialized_data['access_token'] = self._base.token
    deserialized_data['token_expiry'] = _parse_expiry(self.token_expiry)
    return json.dumps(deserialized_data)

  @classmethod
  def for_external_account(cls, filename):
    creds = _get_external_account_credentials_from_file(filename)
    return cls(creds)

  @classmethod
  def from_json(cls, json_data):
    """Instantiate a Credentials object from a JSON description of it.

    The JSON should have been produced by calling .to_json() on the object.

    Args:
        data: dict, A deserialized JSON object.

    Returns:
        An instance of a Credentials subclass.
    """
    data = json.loads(json_data)
    # Rebuild the credentials.
    base = data.get("_base")
    # Init base cred.
    external_account_creds = _get_external_account_credentials_from_info(base)
    creds = cls(external_account_creds)
    # Inject token and expiry.
    creds.access_token = data.get("access_token")
    if (data.get('token_expiry') and
        not isinstance(data['token_expiry'], datetime.datetime)):
      try:
        data['token_expiry'] = datetime.datetime.strptime(
            data['token_expiry'], oauth2client.client.EXPIRY_FORMAT)
      except ValueError:
        data['token_expiry'] = None
    creds.token_expiry = data.get("token_expiry")
    return creds


def _get_external_account_credentials_from_info(info):
  try:
    # Check if configuration corresponds to an AWS credentials.
    creds = aws.Credentials.from_info(info, scopes=DEFAULT_SCOPES)
  except (ValueError, exceptions.RefreshError):
    try:
      # Check if configuration corresponds to an Identity Pool credentials.
      creds = identity_pool.Credentials.from_info(info, scopes=DEFAULT_SCOPES)
    except ValueError:
      # If the configuration is invalid or does not correspond to any
      # supported external_account credentials, no credentials are found.
      return None
  return creds


def _get_external_account_credentials_from_file(filename):
  with io.open(filename, "r", encoding="utf-8") as json_file:
    data = json.load(json_file)
    return _get_external_account_credentials_from_info(data)


def _parse_expiry(expiry):
  if expiry and isinstance(expiry, datetime.datetime):
    return expiry.strftime(oauth2client.client.EXPIRY_FORMAT)
  else:
    return None
