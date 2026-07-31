import warnings
from typing import List, Dict, Any
from caltrans_client import fetch_caltrans_incidents

def scrape_chp_area(area_name: str = None) -> List[Dict[str, Any]]:
    """
    DEPRECATED: Legacy web scraping has been deprecated.
    
    Use `caltrans_client.CaltransAPIClient` or `fetch_caltrans_incidents()` instead.
    This function forwards calls to `caltrans_client.fetch_caltrans_incidents` for backwards compatibility.
    """
    warnings.warn(
        "scrape_chp_area() in scrapper.py is deprecated. Use caltrans_client.fetch_caltrans_incidents() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    print(f"[DEPRECATION WARNING] Using legacy scrapper.py wrapper. Forwarding to caltrans_client...")
    return fetch_caltrans_incidents(area_name=area_name)