export type RestContext = {
  homeDays?: number | null;
  awayDays?: number | null;
  advantageHomeDays?: number | null;
  label?: string | null;
  weekOneNeutralized?: boolean | null;
  shortRestHome?: boolean | null;
  shortRestAway?: boolean | null;
  longRestHome?: boolean | null;
  longRestAway?: boolean | null;
} | null;

export type TravelContext = {
  awayMiles?: number | null;
  awayTimezoneShiftHours?: number | null;
} | null;

export type ScheduleContext = {
  eventId: string;
  gameId?: string;
  season?: number;
  week?: number;
  gameday?: string;
  matchup?: string;
  awayTeam?: string;
  homeTeam?: string;
  available?: boolean;
  reason?: string;
  source?: string;
  rest?: RestContext;
  travel?: TravelContext;
};

export type InjuryProviderMetadata = {
  dataStatus?: string;
  isLive?: boolean;
  lastUpdated?: string | null;
} | null;

export type InjuryContext = {
  awayInjuryScore?: number | null;
  homeInjuryScore?: number | null;
  severity?: string;
  summary?: string;
  keyInjuries?: string[];
  providerMetadata?: InjuryProviderMetadata;
} | null;

export function hasScheduleContext(context: ScheduleContext | null | undefined): boolean {
  return Boolean(context && (context.rest || context.travel || typeof context.week === "number"));
}

export function getRestLabel(rest: RestContext | undefined): string {
  if (!rest) {
    return "Rest data unavailable";
  }

  if (typeof rest.label === "string" && rest.label.trim()) {
    return rest.label;
  }

  if (rest.weekOneNeutralized) {
    return "Offseason / neutral rest";
  }

  return "Rest data unavailable";
}

export function formatTravelMiles(travel: TravelContext | undefined): string | null {
  const awayMiles = travel?.awayMiles;
  if (awayMiles == null) {
    return null;
  }

  return `${awayMiles.toLocaleString()} mi`;
}

export function formatTravelShift(travel: TravelContext | undefined): string | null {
  const awayTimezoneShiftHours = travel?.awayTimezoneShiftHours;
  if (awayTimezoneShiftHours == null) {
    return null;
  }

  const prefix = awayTimezoneShiftHours > 0 ? "+" : "";
  return `${prefix}${awayTimezoneShiftHours}h`;
}

export function formatRestDays(rest: RestContext | undefined, side: "away" | "home"): string {
  if (!rest) {
    return "N/A";
  }

  if (rest.weekOneNeutralized) {
    return "Offseason";
  }

  const days = side === "away" ? rest.awayDays : rest.homeDays;
  return `${days ?? "N/A"} days`;
}

export function formatRestAdvantage(rest: RestContext | undefined): string {
  if (!rest) {
    return "N/A";
  }

  if (rest.weekOneNeutralized) {
    return "Neutral";
  }

  const value = rest.advantageHomeDays;
  if (value == null) {
    return "N/A";
  }

  return `${value > 0 ? "+" : ""}${value} days`;
}

export function getContextReason(context: ScheduleContext | null | undefined): string {
  if (context?.reason) {
    return context.reason;
  }

  return "Schedule context is currently unavailable.";
}

export function isContextFlagEnabled(flag: boolean | null | undefined): boolean {
  return flag === true;
}

export function getInjuryFreshness(injuryContext: InjuryContext | undefined): InjuryProviderMetadata {
  return injuryContext?.providerMetadata ?? null;
}