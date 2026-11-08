"""
====================================================

Delta Products Downloader

====================================================
"""

from core.exchanges.delta.delta_rest import DeltaREST


class DeltaProducts:

    def __init__(self, rest=None):

        # Public product discovery must use the operator-selected venue.
        # Tests and specialized callers can still inject an explicit transport.
        if rest is not None:
            self.rest = rest
        else:
            from core.exchanges.delta.delta_environments import configured_public_rest
            self.rest = configured_public_rest()

    # -------------------------------------------------

    def download(self):

        return self.rest.get(

            "/v2/products"

        )