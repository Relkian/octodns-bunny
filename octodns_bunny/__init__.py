from requests import Session

from octodns import __VERSION__ as octodns_version
from octodns.provider import ProviderException
from octodns.provider.base import BaseProvider

# TODO: remove __VERSION__ with the next major version release
__version__ = __VERSION__ = '0.0.1'


class BunnyClientException(ProviderException):
    pass


class BunnyClientNotFound(BunnyClientException):
    def __init__(self):
        super().__init__('Not Found')


class BunnyClientUnauthorized(BunnyClientException):
    def __init__(self):
        super().__init__('Unauthorized')


class BunnyClient(object):
    API_ROOT = 'https://api.bunny.net'
    RECORD_TYPES = {
        'A': 0,
        'AAAA': 1,
        # CNAME records are *automatically* flattened if used at zone APEX.
        'CNAME': 2,
        'TXT': 3,
        'MX': 4,
        # Proprietary record type which allows to redirect to a specific URL.
        #'RDR': 5,
        # Old proprietary record type for flattened CNAME. Discontinued.
        #'Flatten': 6,
        # Proprietary record type which allows to "CDNify" this record through
        # Bunny CDN.
        # Deprecated, use a standard record type with "Accelerated" and
        # AcceleratedPullZoneId set.
        #'PZ': 7,
        'SRV': 8,
        'CAA': 9,
        'PTR': 10,
        # Proprietary record type which allows to link a record to a Bunny CDN
        # Edge script.
        #'SCR': 11,
        'NS': 12,
    }

    def __init__(self, api_key):
        sess = Session()
        sess.headers.update(
            {
                'AccessKey': api_key,
                'Accept': 'application/json',
                'User-Agent': f'octodns/{octodns_version}'
                ' octodns-digitalocean/{__VERSION__}',
            }
        )
        self._sess = sess
        # We cache the "zone_name" => "zone_id" mapping the first time zones()
        # is called in order to to avoid calling it each time we make a request
        # to an API endpoint, as Bunny's DNS API asks for (internal) zones ID,
        # not zones (domain) names.
        self._zones = {}

    def _request(self, method, path, params=None, data=None):
        url = f'{self.API_ROOT}{path}'

        # "Content-Type: application/json" header is automatically set when json
        # parameter is set.
        r = self._sess.request(method, url, params=params, json=data)

        if r.status_code == 401:
            raise BunnyClientUnauthorized()

        if r.status_code == 404:
            raise BunnyClientNotFound()

        r.raise_for_status()

        return r

    def _cache_zones(self):
        path = '/dnszone'
        page = 1

        while True:
            r = self._request('GET', path, {'page': page}).json()

            for z in r['Items']:
                self._zones[z['Domain']] = z['Id']

            # No more results to request.
            if not r['HasMoreItems'] == True:
                break

            page += 1

    def _get_zone_id(self, zone_name):
        if not self._zones:
            self._cache_zones()

        zone_id = self._zones.get(zone_name)
        if not zone_id:
            raise BunnyClientNotFound()

        return zone_id

    def _update_zones_cache(self, zone_name, zone_id):
        self._zones[zone_name] = zone_id

        return True

    def _handle_record_data(self, record_data, update=False):
        raw_type = record_data.get('Type')

        # Record type and name can't be updated.
        if update:
            if record_data.get('Name') is not None:
                raise BunnyClientException(
                    'Existing record name can\'be' ' updated.'
                )

            if raw_type is not None:
                raise BunnyClientException(
                    'Existing record type can\'be' ' updated.'
                )

            record_data.pop('Name', None)
            record_data.pop('Type', None)

        else:
            # RR "Type" field is required for record creation.
            if not raw_type:
                raise BunnyClientException('No resource record type specified.')

            # Convert standard record types (A, AAAA,...) to Bunny DNS RR ID.
            # type = [v for v in self.RECORD_TYPES.values() if v == raw_type]
            type = self.RECORD_TYPES.get(raw_type)
            # /!\ Record type ID for A id 0!
            if type is None:
                raise BunnyClientException(
                    'Unsupported resource record type:' f' {raw_type}'
                )

            record_data['Type'] = type

        return record_data

    def clear_zones_cache(self):
        self._zones = {}

        return True

    def zones(self):
        if not self._zones:
            self._cache_zones()

        return list(self._zones)

    def zone(self, zone_name):
        zone_id = self._get_zone_id(zone_name)
        path = f'/dnszone/{zone_id}'

        # Returns zone information, *including* DNS records.
        return self._request('GET', path).json()

    def zone_create(self, zone_name):
        path = '/dnszone'
        r = self._request('POST', path, data={'Domain': zone_name}).json()
        # Update zones cache with the ID of the newly crated zone.
        self._update_zones_cache(zone_name, r['Id'])

        return r

    def record_create(self, zone_name, record_data):
        zone_id = self._get_zone_id(zone_name)
        path = f'/dnszone/{zone_id}/records'

        record_data = self._handle_record_data(record_data)

        return self._request('PUT', path, data=record_data).json()

    def record_update(self, zone_name, record_id, record_data):
        zone_id = self._get_zone_id(zone_name)
        path = f'/dnszone/{zone_id}/records/{record_id}'

        record_data = self._handle_record_data(record_data, update=True)

        return self._request('POST', path, data=record_data)

    def record_delete(self, zone_name, record_id):
        zone_id = self._get_zone_id(zone_name)
        path = f'/dnszone/{zone_id}/records/{record_id}'

        return self._request('DELETE', path)


class BunnyProvider(BaseProvider):
    # TODO: implement things
    pass
