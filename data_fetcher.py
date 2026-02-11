"""
Unified data fetcher that orchestrates ATTOM, BatchData, and Census APIs
to enrich property data with real valuations, foreclosure records, and
neighborhood scores.

Usage:
    from data_fetcher import DataFetcher

    fetcher = DataFetcher()
    print(fetcher.status())  # Shows which APIs are configured

    # Enrich a single property
    enriched = fetcher.enrich_property(property_obj)

    # Enrich a list of properties
    enriched_list = fetcher.enrich_properties(property_list)
"""

from typing import List, Dict, Optional
from models import Property
import config

# Lazy imports — only load API modules when keys are configured
_attom = None
_batchdata = None
_census = None


def _get_attom():
    global _attom
    if _attom is None:
        import api_attom
        _attom = api_attom
    return _attom


def _get_batchdata():
    global _batchdata
    if _batchdata is None:
        import api_batchdata
        _batchdata = api_batchdata
    return _batchdata


def _get_census():
    global _census
    if _census is None:
        import api_census
        _census = api_census
    return _census


class DataFetcher:
    """Orchestrates API calls to enrich property data."""

    def __init__(self):
        self.attom_available = bool(config.API_KEYS.get("attom_rapidapi"))
        self.batchdata_available = bool(config.API_KEYS.get("batchdata"))
        self.census_available = True  # Census works without a key (lower rate limit)
        self.hud_available = bool(config.API_KEYS.get("hud"))

    def status(self) -> Dict[str, str]:
        """Show which APIs are configured and ready."""
        return {
            "ATTOM (ARV/valuations)": "Ready" if self.attom_available else "No key — set config.API_KEYS['attom_rapidapi']",
            "BatchData (foreclosure)": "Ready" if self.batchdata_available else "No key — set config.API_KEYS['batchdata']",
            "Census (neighborhood)": "Ready" if config.API_KEYS.get("census") else "Ready (no key, limited to 500 calls/day)",
            "HUD (fair market rent)": "Ready" if self.hud_available else "No key — set config.API_KEYS['hud']",
        }

    def enrich_property(self, prop: Property, skip_arv: bool = False,
                        skip_foreclosure: bool = False,
                        skip_neighborhood: bool = False) -> Property:
        """
        Enrich a single property with real API data.

        Args:
            prop: Property to enrich
            skip_arv: Skip ATTOM AVM lookup
            skip_foreclosure: Skip BatchData foreclosure lookup
            skip_neighborhood: Skip Census neighborhood scoring

        Returns:
            The same Property object, mutated with enriched data
        """
        city_state_zip = f"{prop.city}, {prop.state} {prop.zip_code}"

        # 1. ATTOM — Real ARV from Automated Valuation Model
        if not skip_arv and self.attom_available:
            try:
                attom = _get_attom()
                avm = attom.get_avm(prop.address, city_state_zip)
                if avm and avm.get("value"):
                    prop.estimated_arv = float(avm["value"])
                    # Recalculate metrics with the real ARV
                    prop.calculate_metrics()
            except Exception as e:
                print(f"   ⚠️  ATTOM enrichment failed for {prop.address}: {e}")

        # 2. BatchData — Real foreclosure context
        if not skip_foreclosure and self.batchdata_available:
            try:
                bd = _get_batchdata()
                fc = bd.enrich_foreclosure_context(
                    prop.address, prop.city, prop.state, prop.zip_code
                )
                if fc:
                    if fc.get("foreclosing_entity"):
                        prop.foreclosing_entity = fc["foreclosing_entity"]
                    if fc.get("total_debt"):
                        prop.total_debt = fc["total_debt"]
                    if fc.get("loan_type"):
                        prop.loan_type = fc["loan_type"]
                    if fc.get("default_date"):
                        prop.default_date = fc["default_date"]
                    if fc.get("foreclosure_stage"):
                        prop.foreclosure_stage = fc["foreclosure_stage"]
            except Exception as e:
                print(f"   ⚠️  BatchData enrichment failed for {prop.address}: {e}")

        # 3. Census — Real neighborhood score
        if not skip_neighborhood and self.census_available:
            try:
                census = _get_census()
                score = census.calculate_neighborhood_score(prop.zip_code)
                if score is not None:
                    prop.neighborhood_score = score
                    # Recalculate deal score with real neighborhood data
                    prop.calculate_metrics()
            except Exception as e:
                print(f"   ⚠️  Census enrichment failed for ZIP {prop.zip_code}: {e}")

        return prop

    def enrich_properties(self, properties: List[Property],
                          skip_arv: bool = False,
                          skip_foreclosure: bool = False,
                          skip_neighborhood: bool = False,
                          progress: bool = True) -> List[Property]:
        """
        Enrich a list of properties with real API data.

        Args:
            properties: List of Property objects
            skip_arv: Skip ATTOM calls
            skip_foreclosure: Skip BatchData calls
            skip_neighborhood: Skip Census calls
            progress: Print progress updates

        Returns:
            The same list with enriched data
        """
        total = len(properties)
        enriched_count = 0

        # Cache Census data by zip code to avoid duplicate calls
        census_cache: Dict[str, Optional[int]] = {}

        for i, prop in enumerate(properties):
            if progress and (i + 1) % 10 == 0:
                print(f"   Enriching property {i + 1}/{total}...")

            # Use cached neighborhood scores
            if not skip_neighborhood and self.census_available:
                if prop.zip_code in census_cache:
                    cached_score = census_cache[prop.zip_code]
                    if cached_score is not None:
                        prop.neighborhood_score = cached_score
                    self.enrich_property(prop, skip_neighborhood=True,
                                         skip_arv=skip_arv,
                                         skip_foreclosure=skip_foreclosure)
                else:
                    self.enrich_property(prop, skip_arv=skip_arv,
                                         skip_foreclosure=skip_foreclosure)
                    census_cache[prop.zip_code] = prop.neighborhood_score
            else:
                self.enrich_property(prop, skip_arv=skip_arv,
                                     skip_foreclosure=skip_foreclosure,
                                     skip_neighborhood=True)

            enriched_count += 1

        if progress:
            apis_used = []
            if not skip_arv and self.attom_available:
                apis_used.append("ATTOM")
            if not skip_foreclosure and self.batchdata_available:
                apis_used.append("BatchData")
            if not skip_neighborhood:
                apis_used.append("Census")
            print(f"   Enriched {enriched_count} properties via: {', '.join(apis_used) or 'none'}")

        return properties

    def get_neighborhood_data(self, zip_code: str) -> Optional[Dict]:
        """Get full Census neighborhood data for a ZIP code."""
        census = _get_census()
        return census.get_neighborhood_data(zip_code)

    def get_fair_market_rent(self, county_fips: str) -> Optional[Dict]:
        """Get HUD Fair Market Rent data for a county."""
        if not self.hud_available:
            return None
        census = _get_census()
        return census.get_fair_market_rent(county_fips)
