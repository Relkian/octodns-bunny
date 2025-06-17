import logging
from collections import defaultdict

from requests import Session

from octodns import __VERSION__ as octodns_version
from octodns.provider import ProviderException
from octodns.provider.base import BaseProvider
from octodns.record import Record

# TODO: remove __VERSION__ with the next major version release
__version__ = __VERSION__ = '1.0.0'


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

    def _handle_record_data(self, record_data):
        # Convert standard record types (A, AAAA,...) to Bunny DNS RR ID.
        record_data['Type'] = self.RECORD_TYPES[record_data['Type']]

        return record_data

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

    def zone_records(self, zone_name):
        # Although not strictly necessary, zone_records() simplifies records
        # management for BunnyProvider.
        zone_id = self._get_zone_id(zone_name)
        path = f'/dnszone/{zone_id}'

        # Returns zone information, *including* DNS records.
        r = self._request('GET', path).json()

        records = []
        for record in r['Records']:
            # Convert Bunny DNS RR ID to standard record types (A, AAAA,...).
            try:
                record['Type'] = [
                    k
                    for (k, v) in self.RECORD_TYPES.items()
                    if v == record['Type']
                ][0]
            except IndexError:
                # Unknown record type will be skipped by populate().
                pass

            records.append(record)

        return records

    def record_create(self, zone_name, record_data):
        zone_id = self._get_zone_id(zone_name)
        path = f'/dnszone/{zone_id}/records'

        print(f'{zone_name}: {record_data}')
        record_data = self._handle_record_data(record_data)

        return self._request('PUT', path, data=record_data)

    def record_delete(self, zone_name, record_id):
        zone_id = self._get_zone_id(zone_name)
        path = f'/dnszone/{zone_id}/records/{record_id}'

        return self._request('DELETE', path)


class BunnyProvider(BaseProvider):
    # Geo records are deprecated in favor of dynamic records, see:
    # https://github.com/octodns/octodns/blob/main/docs/geo_records.md
    SUPPORTS_GEO = False
    # Bunny DNS geographic records are based on latitude/longitude, while
    # octoDNS ones are based on country codes.
    SUPPORTS_DYNAMIC = False
    # Requires dynamic records.
    SUPPORTS_POOL_VALUE_STATUS = False
    # Requires dynamic records.
    SUPPORTS_DYNAMIC_SUBNETS = False
    # The same PTR record can return multiple values.
    SUPPORTS_MULTIVALUE_PTR = True
    # Customs root NS can be set in zone settings, but not by updating APEX NS
    # records.
    SUPPORTS_ROOT_NS = False
    # Supported record types.
    SUPPORTS = set(
        ('A', 'AAAA', 'CAA', 'CNAME', 'MX', 'NS', 'PTR', 'SRV', 'TXT')
    )

    def __init__(self, id, api_key, *args, **kwargs):
        self.log = logging.getLogger(f'BunnyProvider[{id}]')
        self.log.debug('__init__: id=%s, api_key=***', id)
        super().__init__(id, *args, **kwargs)
        self._client = BunnyClient(api_key)
        self._zone_records = {}

    def _data_for_multiple(self, _type, records):
        return {
            'ttl': records[0]['Ttl'],
            'type': _type,
            'values': [r['Value'].replace(';', '\\;') for r in records],
        }

    _data_for_A = _data_for_multiple
    _data_for_AAAA = _data_for_multiple
    _data_for_TXT = _data_for_multiple

    def _data_for_CAA(self, _type, records):
        values = []
        for record in records:
            values.append(
                {
                    'flags': record['Flags'],
                    'tag': record['Tag'],
                    'value': record['Value'],
                }
            )

        return {'ttl': records[0]['Ttl'], 'type': _type, 'values': values}

    def _data_for_CNAME(self, _type, records):
        record = records[0]
        return {
            'ttl': record['Ttl'],
            'type': _type,
            'value': f'{record["Value"]}.',
        }

    def _data_for_MX(self, _type, records):
        values = []
        for record in records:
            exchange = '.' if record["Value"] == '.' else f'{record["Value"]}.'
            values.append(
                {'preference': record['Priority'], 'exchange': exchange}
            )

        return {'ttl': records[0]['Ttl'], 'type': _type, 'values': values}

    def _data_for_NS(self, _type, records):
        values = []
        for record in records:
            values.append(f'{record["Value"]}.')

        return {'ttl': records[0]['Ttl'], 'type': _type, 'values': values}

    _data_for_PTR = _data_for_NS

    def _data_for_SRV(self, _type, records):
        values = []
        for record in records:
            target = '.' if record["Value"] == '.' else f'{record["Value"]}.'
            values.append(
                {
                    'port': record['Port'],
                    'priority': record['Priority'],
                    'target': target,
                    'weight': record['Weight'],
                }
            )

        return {'type': _type, 'ttl': records[0]['Ttl'], 'values': values}

    def zone_records(self, zone):
        if zone.name not in self._zone_records:
            try:
                self._zone_records[zone.name] = self._client.zone_records(
                    zone.name[:-1]
                )
            except BunnyClientNotFound:
                return []

        return self._zone_records[zone.name]

    def list_zones(self):
        self.log.debug('list_zones:')

        return sorted([f'{d}.' for d in self._client.zones()])

    def populate(self, zone, target=False, lenient=False):
        self.log.debug(
            'populate: name=%s, target=%s, lenient=%s',
            zone.name,
            target,
            lenient,
        )

        values = defaultdict(lambda: defaultdict(list))
        for record in self.zone_records(zone):
            _type = record['Type']

            if _type not in self.SUPPORTS:
                self.log.warning(
                    'populate: skipping unsupported %s record', _type
                )
                continue

            values[record['Name']][record['Type']].append(record)

        before = len(zone.records)
        for name, types in values.items():
            for _type, records in types.items():
                data_for = getattr(self, f'_data_for_{_type}')
                record = Record.new(
                    zone,
                    name,
                    data_for(_type, records),
                    source=self,
                    lenient=lenient,
                )
                zone.add_record(record, lenient=lenient)

        exists = zone.name in self._zone_records
        self.log.info(
            'populate:   found %s records, exists=%s',
            len(zone.records) - before,
            exists,
        )

        return exists

    def _params_for_multiple(self, record):
        for value in record.values:
            yield {
                'Value': value.replace('\\;', ';'),
                'Name': record.name,
                'Ttl': record.ttl,
                'Type': record._type,
            }

    _params_for_A = _params_for_multiple
    _params_for_AAAA = _params_for_multiple
    _params_for_TXT = _params_for_multiple
    _params_for_NS = _params_for_multiple
    _params_for_PTR = _params_for_multiple

    def _params_for_CAA(self, record):
        for value in record.values:
            yield {
                'Value': value.value,
                'Flags': value.flags,
                'Name': record.name,
                'Tag': value.tag,
                'Ttl': record.ttl,
                'Type': record._type,
            }

    def _params_for_CNAME(self, record):
        yield {
            'Value': record.value,
            'Name': record.name,
            'Ttl': record.ttl,
            'Type': record._type,
        }

    def _params_for_MX(self, record):
        for value in record.values:
            yield {
                'Value': value.exchange,
                'Name': record.name,
                'Priority': value.preference,
                'Ttl': record.ttl,
                'Type': record._type,
            }

    def _params_for_SRV(self, record):
        for value in record.values:
            yield {
                'Value': value.target,
                'Name': record.name,
                'Port': value.port,
                'Priority': value.priority,
                'Ttl': record.ttl,
                'Type': record._type,
                'Weight': value.weight,
            }

    def _apply_Create(self, change):
        new = change.new
        params_for = getattr(self, f'_params_for_{new._type}')
        for params in params_for(new):
            self._client.record_create(new.zone.name[:-1], params)

    def _apply_Update(self, change):
        self._apply_Delete(change)
        self._apply_Create(change)

    def _apply_Delete(self, change):
        existing = change.existing
        zone = existing.zone
        for record in self.zone_records(zone):
            if (
                existing.name == record['Name']
                and existing._type == record['Type']
            ):
                self._client.record_delete(zone.name[:-1], record['Id'])

    def _apply(self, plan):
        desired = plan.desired
        changes = plan.changes
        self.log.debug(
            '_apply: zone=%s, len(changes)=%d', desired.name, len(changes)
        )
        domain_name = desired.name[:-1]
        try:
            self._client.zone(domain_name)
        except BunnyClientNotFound:
            self.log.debug('_apply:   no matching zone, creating domain')
            self._client.zone_create(domain_name)

        for change in changes:
            class_name = change.__class__.__name__
            getattr(self, f'_apply_{class_name}')(change)

        # Clear out the cache if any
        self._zone_records.pop(desired.name, None)
