/**
 * Centralized sportsbook configuration
 * Based on verified sportsbooks in ranked_bet_board.csv
 * 
 * Do not hardcode sportsbook lists in components.
 * Import SPORTSBOOKS_CONFIG instead.
 */

export type SportsbookConfig = {
  key: string;           // Internal key (e.g., "draftkings")
  displayName: string;   // Display name (e.g., "DraftKings")
  baseUrl: string;       // Verified homepage URL
};

/**
 * All sportsbooks currently in SIA data.
 * Ordered by frequency (most common first).
 */
export const SPORTSBOOKS_CONFIG: Record<string, SportsbookConfig> = {
  draftkings: {
    key: "draftkings",
    displayName: "DraftKings",
    baseUrl: "https://sportsbook.draftkings.com",
  },
  betUS: {
    key: "betUS",
    displayName: "BetUS",
    baseUrl: "https://www.betusbet.com",
  },
  fanduel: {
    key: "fanduel",
    displayName: "FanDuel",
    baseUrl: "https://sportsbook.fanduel.com",
  },
  betrivers: {
    key: "betrivers",
    displayName: "BetRivers",
    baseUrl: "https://betrivers.com",
  },
  betonline: {
    key: "betonline",
    displayName: "BetOnline.ag",
    baseUrl: "https://www.betonline.ag",
  },
  mybookie: {
    key: "mybookie",
    displayName: "MyBookie.ag",
    baseUrl: "https://www.mybookie.ag",
  },
  bovada: {
    key: "bovada",
    displayName: "Bovada",
    baseUrl: "https://www.bovada.lv",
  },
  lowvig: {
    key: "lowvig",
    displayName: "LowVig.ag",
    baseUrl: "https://www.lowvig.ag",
  },
};

/**
 * Get sportsbook config by display name (as it appears in data).
 * Handles variations and normalizes to config entry.
 */
export function getSportsbookConfig(displayName: string): SportsbookConfig | undefined {
  if (!displayName) return undefined;

  // Normalize input
  const normalized = displayName.trim();

  // Try exact match in values first
  for (const config of Object.values(SPORTSBOOKS_CONFIG)) {
    if (config.displayName === normalized) {
      return config;
    }
  }

  // Try key match
  const key = Object.keys(SPORTSBOOKS_CONFIG).find(
    (k) => k.toLowerCase() === normalized.toLowerCase()
  );
  if (key) return SPORTSBOOKS_CONFIG[key];

  // Try partial match
  const lowerNormalized = normalized.toLowerCase();
  for (const config of Object.values(SPORTSBOOKS_CONFIG)) {
    if (
      config.displayName.toLowerCase().includes(lowerNormalized) ||
      lowerNormalized.includes(config.displayName.toLowerCase())
    ) {
      return config;
    }
  }

  return undefined;
}

/**
 * Get all available sportsbook display names.
 */
export function getAllSportsbookNames(): string[] {
  return Object.values(SPORTSBOOKS_CONFIG).map((sb) => sb.displayName);
}

/**
 * Verify that a sportsbook is known/supported.
 */
export function isSportsbookSupported(displayName: string): boolean {
  return getSportsbookConfig(displayName) !== undefined;
}
