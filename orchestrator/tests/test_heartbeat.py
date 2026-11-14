import unittest

from heartbeat import format_mac, parse_heartbeat


class HeartbeatTests(unittest.TestCase):
    def test_reads_mac_and_rssi(self) -> None:
        raw = b'{"mac":"90:15:06:FB:7C:08","ok":1,"rssi":-56}'
        self.assertEqual(
            parse_heartbeat(raw),
            {"mac": "901506fb7c08", "rssi": -56},
        )

    def test_rejects_a_light_packet(self) -> None:
        self.assertIsNone(parse_heartbeat(b'{"on":false}'))

    def test_rejects_a_short_mac(self) -> None:
        self.assertIsNone(parse_heartbeat(b'{"mac":"9015","ok":1}'))

    def test_formats_mac(self) -> None:
        self.assertEqual(format_mac("f024f9940324"), "F0:24:F9:94:03:24")


if __name__ == "__main__":
    unittest.main()
