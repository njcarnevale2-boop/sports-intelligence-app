type OpportunitySummary = {
  matchup: string;
  pick: string;
  book: string;
  price: number;
  modelProbability: number;
  impliedProbability: number;
  edge: number;
  evPerDollar: number;
  confidence: number;
};

type GameProjectionSummary = {
  awayTeam: string;
  homeTeam: string;
  model: {
    marginHome: number;
    total: number;
    projectedScore: {
      away: number;
      home: number;
    };
  };
  market: {
    marginHome: number;
    homeSpread: number;
    total: number;
  };
  spreadAnalysis: {
    edgePoints: number;
    homeCoverProbability: number;
  };
};

type ScheduleContextSummary = {
  week: number;
  awayTeam: string;
  homeTeam: string;
  rest: {
    label: string;
    weekOneNeutralized: boolean;
    shortRestHome: boolean;
    shortRestAway: boolean;
  };
  travel: {
    awayMiles: number | null;
    awayTimezoneShiftHours: number | null;
  };
};

type ExecutiveSummaryProps = {
  opportunity: OpportunitySummary;
  projection?: GameProjectionSummary | null;
  context?: ScheduleContextSummary | null;
};

function formatOdds(price: number) {
  return price > 0 ? `+${price}` : `${price}`;
}

function describeTravel(
  miles: number | null
) {
  if (miles === null) return "Travel impact is unavailable";

  if (miles < 500) {
    return `Travel is relatively light at approximately ${miles.toFixed(
      0
    )} miles`;
  }

  if (miles < 1500) {
    return `Travel is moderate at approximately ${miles.toFixed(
      0
    )} miles`;
  }

  return `Travel is significant at approximately ${miles.toFixed(
    0
  )} miles`;
}

export default function ExecutiveSummary({
  opportunity,
  projection,
  context,
}: ExecutiveSummaryProps) {
  const probabilityGap =
    opportunity.modelProbability -
    opportunity.impliedProbability;

  const sentences: string[] = [];

  sentences.push(
    `The model currently identifies ${opportunity.pick} as a high-value position, assigning a ${opportunity.modelProbability.toFixed(
      1
    )}% probability compared with ${opportunity.impliedProbability.toFixed(
      1
    )}% implied by the market.`
  );

  sentences.push(
    `That creates a ${probabilityGap.toFixed(
      1
    )}-percentage-point probability gap and a current model edge of +${opportunity.edge.toFixed(
      1
    )}%.`
  );

  if (projection) {
    sentences.push(
      `At the matchup level, the model projects ${projection.awayTeam} ${projection.model.projectedScore.away.toFixed(
        1
      )} and ${projection.homeTeam} ${projection.model.projectedScore.home.toFixed(
        1
      )}.`
    );

    const marginDifference =
      projection.model.marginHome -
      projection.market.marginHome;

    if (Math.abs(marginDifference) >= 3) {
      sentences.push(
        `There is a meaningful disagreement between the internal projection and the market, with the home-team margin differing by ${Math.abs(
          marginDifference
        ).toFixed(1)} points.`
      );
    } else {
      sentences.push(
        `The internal game projection and market spread are relatively close, so most of the current value is being created by price and probability rather than a major spread disagreement.`
      );
    }

    if (
      projection.model.total !==
      projection.market.total
    ) {
      sentences.push(
        `The model total is ${projection.model.total.toFixed(
          1
        )} versus a market total of ${projection.market.total.toFixed(
          1
        )}.`
      );
    }
  }

  if (context) {
    if (context.rest.weekOneNeutralized) {
      sentences.push(
        `Rest is treated as neutral because this is Week ${context.week} following the offseason.`
      );
    } else {
      sentences.push(
        `The schedule model currently classifies the rest situation as ${context.rest.label.toLowerCase()}.`
      );
    }

    if (context.travel.awayMiles !== null) {
      sentences.push(
        `${describeTravel(
          context.travel.awayMiles
        )}${
          context.travel.awayTimezoneShiftHours !==
          null
            ? ` with a ${context.travel.awayTimezoneShiftHours.toFixed(
                1
              )}-hour timezone shift`
            : ""
        }.`
      );
    }

    if (
      context.rest.shortRestAway ||
      context.rest.shortRestHome
    ) {
      const shortRestTeams: string[] = [];

      if (context.rest.shortRestAway) {
        shortRestTeams.push(context.awayTeam);
      }

      if (context.rest.shortRestHome) {
        shortRestTeams.push(context.homeTeam);
      }

      sentences.push(
        `${shortRestTeams.join(
          " and "
        )} ${
          shortRestTeams.length > 1 ? "are" : "is"
        } operating on a short-rest schedule, which should remain part of the pregame risk review.`
      );
    }
  }

  sentences.push(
    `The best current price is available at ${opportunity.book} for ${formatOdds(
      opportunity.price
    )}, with expected value of +$${opportunity.evPerDollar.toFixed(
      3
    )} per $1 risked and a confidence score of ${opportunity.confidence}.`
  );

  return (
    <section className="rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,#121821_0%,#0C1118_100%)] p-8 lg:p-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Executive Summary
          </p>

          <h2 className="mt-3 text-3xl font-semibold tracking-tight">
            Why this opportunity matters.
          </h2>
        </div>

        <span className="rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-xs text-zinc-500">
          Data-driven analysis
        </span>
      </div>

      <div className="mt-6 max-w-4xl space-y-4">
        {sentences.map((sentence, index) => (
          <p
            key={index}
            className="text-base leading-8 text-zinc-400"
          >
            {sentence}
          </p>
        ))}
      </div>

      <div className="mt-8 grid gap-3 border-t border-white/[0.07] pt-6 sm:grid-cols-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
            Probability Gap
          </p>

          <p className="mt-2 text-xl font-semibold text-emerald-400">
            +{probabilityGap.toFixed(1)} pts
          </p>
        </div>

        <div>
          <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
            Expected Value
          </p>

          <p className="mt-2 text-xl font-semibold">
            +${opportunity.evPerDollar.toFixed(3)}
          </p>
        </div>

        <div>
          <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
            Confidence
          </p>

          <p className="mt-2 text-xl font-semibold">
            {opportunity.confidence}
          </p>
        </div>
      </div>
    </section>
  );
}