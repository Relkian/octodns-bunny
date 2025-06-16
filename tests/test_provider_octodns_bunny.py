from os.path import dirname, join
from unittest import TestCase
from unittest.mock import Mock, call

import requests
import requests_mock

from octodns.provider.yaml import YamlProvider
from octodns.record import Record
from octodns.zone import Zone

from octodns_bunny import (
    BunnyClientNotFound,
    BunnyClientUnauthorized,
    BunnyProvider,
)


class TestBunnyProvider(TestCase):
    expected = Zone('unit.tests.', [])
    source = YamlProvider('test', join(dirname(__file__), 'config'))
    source.populate(expected)

    @requests_mock.Mocker()
    def test_list_zones(self, m):
        provider = BunnyProvider('test', 'token')

        with open('tests/fixtures/dnszone-page1.json') as fh:
            m.get('/dnszone', status_code=200, text=fh.read())
        with open('tests/fixtures/dnszone-page2.json') as fh:
            m.get('/dnszone?page=2', status_code=200, text=fh.read())

        zones = [
            'acme-inc.com.',
            'another-example.com.',
            'example.fr.',
            'example.net.',
            'jhdjzdjhehjeejhej.net.',
            'unit.tests.',
        ]
        self.assertEqual(provider.list_zones(), zones)

        # Another call to provider.list_zones() should return the same values,
        # served from cache.
        resp = Mock()
        resp.json = Mock()
        provider._client._request = Mock(return_value=resp)

        self.assertEqual(provider.list_zones(), zones)

        # _client._request() has never been called.
        provider._client._request.assert_not_called()

    @requests_mock.Mocker()
    def test_zone_records(self, m):
        provider = BunnyProvider('test', 'token')
        zone = Zone('example.net.', [])

        with open('tests/fixtures/dnszone-page1.json') as fh:
            m.get('/dnszone', status_code=200, text=fh.read())
        with open('tests/fixtures/dnszone-page2.json') as fh:
            m.get('/dnszone?page=2', status_code=200, text=fh.read())
        with open('tests/fixtures/zone-525579.json') as fh:
            m.get('/dnszone/525579', status_code=200, text=fh.read())

        records = [
            {
                'Accelerated': False,
                'AcceleratedPullZoneId': 0,
                'Comment': None,
                'Disabled': False,
                'EnviromentalVariables': [],
                'Flags': 0,
                'GeolocationInfo': None,
                'GeolocationLatitude': 0.0,
                'GeolocationLongitude': 0.0,
                'IPGeoLocationInfo': None,
                'Id': 8891927,
                'LatencyZone': None,
                'LinkName': '',
                'MonitorStatus': 0,
                'MonitorType': 0,
                'Name': '',
                'Port': 0,
                'Priority': 0,
                'SmartRoutingType': 0,
                'Tag': '',
                'Ttl': 300,
                'Type': 'A',
                'Value': '127.0.0.1',
                'Weight': 100,
            },
            {
                'Accelerated': False,
                'AcceleratedPullZoneId': 0,
                'Comment': None,
                'Disabled': False,
                'EnviromentalVariables': [],
                'Flags': 0,
                'GeolocationInfo': None,
                'GeolocationLatitude': 0.0,
                'GeolocationLongitude': 0.0,
                'IPGeoLocationInfo': None,
                'Id': 8891929,
                'LatencyZone': None,
                'LinkName': '',
                'MonitorStatus': 0,
                'MonitorType': 0,
                'Name': '',
                'Port': 0,
                'Priority': 10,
                'SmartRoutingType': 0,
                'Tag': '',
                'Ttl': 300,
                'Type': 'MX',
                'Value': '.',
                'Weight': 0,
            },
        ]
        self.assertEqual(provider.zone_records(zone), records)

        # Unexisting zone must return an empty records list.
        zone = Zone('unit-missing.test.', [])
        self.assertEqual(provider.zone_records(zone), [])

    @requests_mock.Mocker()
    def test_populate(self, m):
        provider = BunnyProvider('test', 'token')

        # Invalid API key or access denied.
        m.get(
            requests_mock.ANY,
            status_code=401,
            text='{"Message":"Authorization has been denied for this'
            ' request."}',
        )
        with self.assertRaises(BunnyClientUnauthorized) as ctx:
            zone = Zone('unit.tests.', [])
            provider.populate(zone)

        self.assertEqual('Unauthorized', str(ctx.exception))

        # Not Found.
        m.get(requests_mock.ANY, status_code=404, text='')
        with self.assertRaises(BunnyClientNotFound) as ctx:
            zone = Zone('unit.tests.', [])
            provider.list_zones()

        self.assertEqual('Not Found', str(ctx.exception))

        # Internal server error.
        m.get(requests_mock.ANY, status_code=500, text='')

        with self.assertRaises(requests.HTTPError) as ctx:
            zone = Zone('unit.tests.', [])
            provider.populate(zone)

        self.assertEqual(500, ctx.exception.response.status_code)

        # Domains list.
        with open('tests/fixtures/dnszone-page1.json') as fh:
            m.get('/dnszone', status_code=200, text=fh.read())
        with open('tests/fixtures/dnszone-page2.json') as fh:
            m.get('/dnszone?page=2', status_code=200, text=fh.read())

        # Zone: unit.tests.
        with open('tests/fixtures/zone-525638.json') as fh:
            m.get('/dnszone/525638', status_code=200, text=fh.read())

        zone = Zone('unit.tests.', [])
        provider.populate(zone)
        # This zone must contain 11 records.
        self.assertEqual(11, len(zone.records))
        # One record to update.
        # "hop 300 IN A 127.0.0.21" => "hop 300 IN A 127.0.0.23"
        changes = self.expected.changes(zone, provider)
        self.assertEqual(1, len(changes))

        # 2nd populate makes no network calls/all from cache.
        zone = Zone('unit.tests.', [])
        provider.populate(zone)
        self.assertEqual(11, len(zone.records))

        # Will raise KeyError if zone is not cached.
        del provider._zone_records[zone.name]
        # No final dot used for zone name in Bunny client.
        # "unit.tests." => "unit.tests"
        del provider._client._zones[zone.name[:-1]]

        # Unexisting zone doesn't populate anything.
        zone = Zone('unit-missing.test.', [])
        provider.populate(zone)
        self.assertEqual(set(), zone.records)

        # Reset provider.
        provider = BunnyProvider('test', 'token')

        # Zone: unit.tests (no record to update).
        with open('tests/fixtures/zone-525638-no-changes.json') as fh:
            m.get('/dnszone/525638', status_code=200, text=fh.read())

        zone = Zone('unit.tests.', [])
        provider.populate(zone)
        # This zone must contain 11 records.
        self.assertEqual(11, len(zone.records))
        # No diffs == no changes.
        changes = self.expected.changes(zone, provider)
        self.assertEqual(0, len(changes))

        # Zone: unit.tests (unsupported record type: NAPTR).
        with open(
            'tests/fixtures/zone-525638-unsupported-record-type.json'
        ) as fh:
            m.get('/dnszone/525638', status_code=200, text=fh.read())

        # Unsupported record type must be skipped.
        with self.assertLogs('BunnyProvider[test]', level='WARNING') as logger:
            provider = BunnyProvider('test', 'token')
            zone = Zone('unit.tests.', [])
            provider.populate(zone)

        self.assertEqual(
            [
                'WARNING:BunnyProvider[test]:populate: skipping unsupported'
                ' XXXX record'
            ],
            logger.output,
        )

    def test_apply(self):
        provider = BunnyProvider('test', 'token')
        resp = Mock()
        resp.json = Mock()
        provider._client._request = Mock(return_value=resp)

        domain_after_creation = {
            'Id': 525638,
            'Domain': 'unit.tests',
            'Records': [],
            'DateModified': '2025-06-07T23:13:09',
            'DateCreated': '2025-06-07T23:13:09',
            'NameserversDetected': True,
            'CustomNameserversEnabled': False,
            'Nameserver1': 'kiki.bunny.net',
            'Nameserver2': 'coco.bunny.net',
            'SoaEmail': 'hostmaster@bunny.net',
            'NameserversNextCheck': '2025-06-07T23:18:09',
            'LoggingEnabled': False,
            'LoggingIPAnonymizationEnabled': True,
            'LogAnonymizationType': 0,
            'DnsSecEnabled': False,
            'CertificateKeyType': 0,
        }

        # Non-existent domain, create everything.
        resp.json.side_effect = [
            # No zone in populate().
            BunnyClientNotFound,
            # No domain during apply().
            BunnyClientNotFound,
            domain_after_creation,
        ]

        plan = provider.plan(self.expected)

        n = len(self.expected.records)
        self.assertEqual(n, len(plan.changes))
        self.assertEqual(n, provider.apply(plan))
        self.assertFalse(plan.exists)

        provider._client._request.assert_has_calls(
            [
                # Listed zones when plan() has been called.
                call('GET', '/dnszone', {'page': 1}),
                # Listed zones when apply() has been called, as previous call
                # raised a BunnyClientNotFound() exception in plan().
                call('GET', '/dnszone', {'page': 1}),
                # Created the zone.
                call('POST', '/dnszone', data={'Domain': 'unit.tests'}),
                # Created zones records.
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': '127.0.0.11',
                        'Name': '',
                        'Ttl': 0,
                        'Type': 0,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={'Value': '::23', 'Name': '', 'Ttl': 0, 'Type': 1},
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'example-ca.com',
                        'Flags': 123,
                        'Name': '',
                        'Tag': 'issue',
                        'Ttl': 300,
                        'Type': 9,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'digicert.com',
                        'Flags': 128,
                        'Name': '',
                        'Tag': 'issuewild',
                        'Ttl': 300,
                        'Type': 9,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': '.',
                        'Name': '',
                        'Priority': 10,
                        'Ttl': 300,
                        'Type': 4,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'v=spf1 -all',
                        'Name': '',
                        'Ttl': 300,
                        'Type': 3,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'test.com.',
                        'Name': '7.8.9.1',
                        'Ttl': 300,
                        'Type': 10,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'test2.com.',
                        'Name': '7.8.9.1',
                        'Ttl': 300,
                        'Type': 10,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'sip.example.com.',
                        'Name': '_sip._tcp',
                        'Port': 5060,
                        'Priority': 100,
                        'Ttl': 300,
                        'Type': 8,
                        'Weight': 100,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': '127.0.0.23',
                        'Name': 'hop',
                        'Ttl': 300,
                        'Type': 0,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'mail.exaple.com.',
                        'Name': 'submail',
                        'Priority': 10,
                        'Ttl': 300,
                        'Type': 4,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'example.com.',
                        'Name': 'subtest',
                        'Ttl': 300,
                        'Type': 2,
                    },
                ),
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': 'ns1.example.com.',
                        'Name': 'subzone',
                        'Ttl': 300,
                        'Type': 12,
                    },
                ),
            ]
        )

        self.assertEqual(16, provider._client._request.call_count)

        provider._client._request.reset_mock()

        # Fake records list returned by provider._client.zone_records().
        provider._client.zone_records = Mock(
            return_value=[
                {
                    'Id': 8893894,
                    # /!\ Bunny DNS RR ID (0, 1, ...) must be converted to
                    # standard record types (A, AAAA,...) here as the conversion
                    # is done in provider._client.zone_records() itself.
                    'Type': 'A',
                    'Ttl': 300,
                    'Value': '127.0.0.21',
                    'Name': 'hop',
                    'Weight': 100,
                    'Priority': 0,
                    'Port': 0,
                    'Flags': 0,
                    'Tag': '',
                    'Accelerated': False,
                    'AcceleratedPullZoneId': 0,
                    'LinkName': '',
                    'IPGeoLocationInfo': None,
                    'GeolocationInfo': None,
                    'MonitorStatus': 0,
                    'MonitorType': 0,
                    'GeolocationLatitude': 0,
                    'GeolocationLongitude': 0,
                    'EnviromentalVariables': [],
                    'LatencyZone': None,
                    'SmartRoutingType': 0,
                    'Disabled': False,
                    'Comment': None,
                },
                {
                    'Id': 8894029,
                    'Type': 'A',
                    'Ttl': 0,
                    'Value': '127.0.0.11',
                    'Name': '',
                    'Weight': 0,
                    'Priority': 0,
                    'Port': 0,
                    'Flags': 0,
                    'Tag': '',
                    'Accelerated': False,
                    'AcceleratedPullZoneId': 0,
                    'LinkName': '',
                    'IPGeoLocationInfo': None,
                    'GeolocationInfo': None,
                    'MonitorStatus': 0,
                    'MonitorType': 0,
                    'GeolocationLatitude': 0,
                    'GeolocationLongitude': 0,
                    'EnviromentalVariables': [],
                    'LatencyZone': None,
                    'SmartRoutingType': 0,
                    'Disabled': False,
                    'Comment': None,
                },
                {
                    'Id': 8895836,
                    'Type': 'AAAA',
                    'Ttl': 0,
                    'Value': '::23',
                    'Name': '',
                    'Weight': 100,
                    'Priority': 0,
                    'Port': 0,
                    'Flags': 0,
                    'Tag': '',
                    'Accelerated': False,
                    'AcceleratedPullZoneId': 0,
                    'LinkName': '',
                    'IPGeoLocationInfo': None,
                    'GeolocationInfo': None,
                    'MonitorStatus': 0,
                    'MonitorType': 0,
                    'GeolocationLatitude': 0,
                    'GeolocationLongitude': 0,
                    'EnviromentalVariables': [],
                    'LatencyZone': None,
                    'SmartRoutingType': 0,
                    'Disabled': False,
                    'Comment': None,
                },
            ]
        )

        # Domain exists as zone_records() has returned the records list, so we
        # don't care about return.
        resp.json.side_effect = ['{}']

        wanted = Zone('unit.tests.', [])
        wanted.add_record(
            Record.new(
                # Update IP address.
                wanted,
                'hop',
                {'ttl': 300, 'type': 'A', 'value': '127.0.0.22'},
            )
        )

        # Delete 2 records, update 1 record (= 3 DELETE + 1 POST).
        plan = provider.plan(wanted)
        self.assertTrue(plan.exists)
        self.assertEqual(3, len(plan.changes))
        self.assertEqual(3, provider.apply(plan))

        # recreate for update, and delete for the 2 parts of the other
        provider._client._request.assert_has_calls(
            [
                # Get records list.
                call('GET', '/dnszone/525638'),
                # Delete record "@ 0 IN A 127.0.0.11".
                call('DELETE', '/dnszone/525638/records/8894029'),
                # Delete record "@ 0 IN AAAA ::23".
                call('DELETE', '/dnszone/525638/records/8895836'),
                # Delete record "hop 300 IN A 127.0.0.21" for update.
                call('DELETE', '/dnszone/525638/records/8893894'),
                # Create record "hop 300 IN A 127.0.0.22" with updated value.
                call(
                    'PUT',
                    '/dnszone/525638/records',
                    data={
                        'Value': '127.0.0.22',
                        'Name': 'hop',
                        'Ttl': 300,
                        'Type': 0,
                    },
                ),
            ]
        )
