"""Endpoint environment metadata must never mislabel production as testnet."""

import unittest

from scripts.capture_l2_continuous_pipeline import classify_endpoint_environment


class CaptureEndpointEnvironmentTests(unittest.TestCase):
    def test_delta_india_production_public_socket(self):
        self.assertEqual(
            classify_endpoint_environment("wss://public-socket.india.delta.exchange"),
            "PRODUCTION",
        )

    def test_delta_india_testnet_public_socket(self):
        self.assertEqual(
            classify_endpoint_environment("wss://socket-ind-pub.testnet.deltaex.org"),
            "SANDBOX / TESTNET",
        )

    def test_unknown_endpoint_fails_closed(self):
        self.assertEqual(
            classify_endpoint_environment("wss://example.invalid"),
            "UNKNOWN",
        )

    def test_lookalike_hostname_is_not_trusted(self):
        self.assertEqual(
            classify_endpoint_environment("wss://public-socket.india.delta.exchange.attacker.invalid"),
            "UNKNOWN",
        )


if __name__ == "__main__":
    unittest.main()
