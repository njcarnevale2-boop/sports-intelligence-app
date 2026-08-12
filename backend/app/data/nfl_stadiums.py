"""
NFL stadium metadata for all 32 teams.

Sources: official team websites, stadium capacities, and publicly available
GPS coordinates. Coordinates are city-centre / stadium approximate positions
accurate to within ~0.01°.

roofType values : OUTDOOR | DOME | RETRACTABLE
surface values  : grass | artificial
"""
from __future__ import annotations

from typing import Dict, Optional

NFL_STADIUMS: Dict[str, Dict] = {
    "ARI": {
        "team": "Arizona Cardinals",
        "stadium": "State Farm Stadium",
        "city": "Glendale", "state": "AZ",
        "latitude": 33.5277, "longitude": -112.2626,
        "roofType": "RETRACTABLE", "surface": "grass",
    },
    "ATL": {
        "team": "Atlanta Falcons",
        "stadium": "Mercedes-Benz Stadium",
        "city": "Atlanta", "state": "GA",
        "latitude": 33.7554, "longitude": -84.4010,
        "roofType": "RETRACTABLE", "surface": "artificial",
    },
    "BAL": {
        "team": "Baltimore Ravens",
        "stadium": "M&T Bank Stadium",
        "city": "Baltimore", "state": "MD",
        "latitude": 39.2780, "longitude": -76.6228,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "BUF": {
        "team": "Buffalo Bills",
        "stadium": "Highmark Stadium",
        "city": "Orchard Park", "state": "NY",
        "latitude": 42.7738, "longitude": -78.7870,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "CAR": {
        "team": "Carolina Panthers",
        "stadium": "Bank of America Stadium",
        "city": "Charlotte", "state": "NC",
        "latitude": 35.2258, "longitude": -80.8528,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "CHI": {
        "team": "Chicago Bears",
        "stadium": "Soldier Field",
        "city": "Chicago", "state": "IL",
        "latitude": 41.8623, "longitude": -87.6167,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "CIN": {
        "team": "Cincinnati Bengals",
        "stadium": "Paycor Stadium",
        "city": "Cincinnati", "state": "OH",
        "latitude": 39.0954, "longitude": -84.5160,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "CLE": {
        "team": "Cleveland Browns",
        "stadium": "Cleveland Browns Stadium",
        "city": "Cleveland", "state": "OH",
        "latitude": 41.5061, "longitude": -81.6995,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "DAL": {
        "team": "Dallas Cowboys",
        "stadium": "AT&T Stadium",
        "city": "Arlington", "state": "TX",
        "latitude": 32.7480, "longitude": -97.0931,
        "roofType": "RETRACTABLE", "surface": "artificial",
    },
    "DEN": {
        "team": "Denver Broncos",
        "stadium": "Empower Field at Mile High",
        "city": "Denver", "state": "CO",
        "latitude": 39.7439, "longitude": -105.0201,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "DET": {
        "team": "Detroit Lions",
        "stadium": "Ford Field",
        "city": "Detroit", "state": "MI",
        "latitude": 42.3400, "longitude": -83.0456,
        "roofType": "DOME", "surface": "artificial",
    },
    "GB": {
        "team": "Green Bay Packers",
        "stadium": "Lambeau Field",
        "city": "Green Bay", "state": "WI",
        "latitude": 44.5013, "longitude": -88.0622,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "HOU": {
        "team": "Houston Texans",
        "stadium": "NRG Stadium",
        "city": "Houston", "state": "TX",
        "latitude": 29.6847, "longitude": -95.4107,
        "roofType": "RETRACTABLE", "surface": "grass",
    },
    "IND": {
        "team": "Indianapolis Colts",
        "stadium": "Lucas Oil Stadium",
        "city": "Indianapolis", "state": "IN",
        "latitude": 39.7601, "longitude": -86.1639,
        "roofType": "RETRACTABLE", "surface": "artificial",
    },
    "JAX": {
        "team": "Jacksonville Jaguars",
        "stadium": "EverBank Stadium",
        "city": "Jacksonville", "state": "FL",
        "latitude": 30.3240, "longitude": -81.6373,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "KC": {
        "team": "Kansas City Chiefs",
        "stadium": "GEHA Field at Arrowhead Stadium",
        "city": "Kansas City", "state": "MO",
        "latitude": 39.0489, "longitude": -94.4839,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "LAC": {
        "team": "Los Angeles Chargers",
        "stadium": "SoFi Stadium",
        "city": "Inglewood", "state": "CA",
        "latitude": 33.9535, "longitude": -118.3392,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "LAR": {
        "team": "Los Angeles Rams",
        "stadium": "SoFi Stadium",
        "city": "Inglewood", "state": "CA",
        "latitude": 33.9535, "longitude": -118.3392,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "LV": {
        "team": "Las Vegas Raiders",
        "stadium": "Allegiant Stadium",
        "city": "Las Vegas", "state": "NV",
        "latitude": 36.0909, "longitude": -115.1831,
        "roofType": "DOME", "surface": "artificial",
    },
    "MIA": {
        "team": "Miami Dolphins",
        "stadium": "Hard Rock Stadium",
        "city": "Miami Gardens", "state": "FL",
        "latitude": 25.9580, "longitude": -80.2388,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "MIN": {
        "team": "Minnesota Vikings",
        "stadium": "U.S. Bank Stadium",
        "city": "Minneapolis", "state": "MN",
        "latitude": 44.9736, "longitude": -93.2575,
        "roofType": "DOME", "surface": "artificial",
    },
    "NE": {
        "team": "New England Patriots",
        "stadium": "Gillette Stadium",
        "city": "Foxborough", "state": "MA",
        "latitude": 42.0909, "longitude": -71.2643,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "NO": {
        "team": "New Orleans Saints",
        "stadium": "Caesars Superdome",
        "city": "New Orleans", "state": "LA",
        "latitude": 29.9511, "longitude": -90.0812,
        "roofType": "DOME", "surface": "artificial",
    },
    "NYG": {
        "team": "New York Giants",
        "stadium": "MetLife Stadium",
        "city": "East Rutherford", "state": "NJ",
        "latitude": 40.8135, "longitude": -74.0745,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "NYJ": {
        "team": "New York Jets",
        "stadium": "MetLife Stadium",
        "city": "East Rutherford", "state": "NJ",
        "latitude": 40.8135, "longitude": -74.0745,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "PHI": {
        "team": "Philadelphia Eagles",
        "stadium": "Lincoln Financial Field",
        "city": "Philadelphia", "state": "PA",
        "latitude": 39.9008, "longitude": -75.1675,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "PIT": {
        "team": "Pittsburgh Steelers",
        "stadium": "Acrisure Stadium",
        "city": "Pittsburgh", "state": "PA",
        "latitude": 40.4468, "longitude": -80.0158,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "SEA": {
        "team": "Seattle Seahawks",
        "stadium": "Lumen Field",
        "city": "Seattle", "state": "WA",
        "latitude": 47.5952, "longitude": -122.3316,
        "roofType": "OUTDOOR", "surface": "artificial",
    },
    "SF": {
        "team": "San Francisco 49ers",
        "stadium": "Levi's Stadium",
        "city": "Santa Clara", "state": "CA",
        "latitude": 37.4033, "longitude": -121.9694,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "TB": {
        "team": "Tampa Bay Buccaneers",
        "stadium": "Raymond James Stadium",
        "city": "Tampa", "state": "FL",
        "latitude": 27.9759, "longitude": -82.5033,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "TEN": {
        "team": "Tennessee Titans",
        "stadium": "Nissan Stadium",
        "city": "Nashville", "state": "TN",
        "latitude": 36.1665, "longitude": -86.7713,
        "roofType": "OUTDOOR", "surface": "grass",
    },
    "WAS": {
        "team": "Washington Commanders",
        "stadium": "Northwest Stadium",
        "city": "Landover", "state": "MD",
        "latitude": 38.9076, "longitude": -76.8645,
        "roofType": "OUTDOOR", "surface": "grass",
    },
}

# Neutral weather used when a stadium has no outdoor exposure
NEUTRAL_WEATHER: dict = {
    "temperature": 72.0,
    "windSpeed": 0.0,
    "windGust": 0.0,
    "windDirection": "N/A",
    "precipitationProbability": 0.0,
    "precipitationAmount": 0.0,
    "humidity": 50.0,
    "conditions": "Indoor — climate controlled",
    "stadiumType": "DOME",
    "surface": "artificial",
}


def get_stadium(team_code: str) -> Optional[Dict]:
    """Return stadium metadata for a team, or None if unknown."""
    return NFL_STADIUMS.get(str(team_code).upper().strip())
