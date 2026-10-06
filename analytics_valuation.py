"""User-input equity valuation. No market-data calls; Decimal math until serialization."""
from datetime import date
from decimal import Decimal as D, localcontext
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from tracker import PortfolioError

Amount = Annotated[D, Field(ge=-D('1e15'), le=D('1e15'), max_digits=28, decimal_places=12)]
Nonnegative = Annotated[D, Field(ge=0, le=D('1e15'), max_digits=28, decimal_places=12)]
Positive = Annotated[D, Field(gt=0, le=D('1e15'), max_digits=28, decimal_places=12)]
Rate = Annotated[D, Field(ge=0, le=100, max_digits=16, decimal_places=12)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ForecastYear(Model):
    ebit: Amount
    tax_rate: Rate
    depreciation: Nonnegative
    capex: Nonnegative
    change_nwc: Amount


class DCFCase(Model):
    name: Literal['Bear', 'Base', 'Bull']
    wacc: Annotated[D, Field(gt=0, le=100, max_digits=16, decimal_places=12)]
    growth: Annotated[D, Field(gt=-100, le=20, max_digits=16, decimal_places=12)] | None = None
    exit_multiple: Annotated[D, Field(gt=0, le=1000, max_digits=16, decimal_places=12)] | None = None
    years: list[ForecastYear] = Field(min_length=1, max_length=10)


class Peer(Model):
    name: str = Field(min_length=1, max_length=80)
    enterprise_value: Amount | None = None
    equity_value: Nonnegative | None = None
    revenue: Amount | None = None
    ebitda: Amount | None = None
    net_income: Amount | None = None


class Comps(Model):
    period: str = Field(min_length=1, max_length=80)
    revenue: Amount | None = None
    ebitda: Amount | None = None
    net_income: Amount | None = None
    peers: list[Peer] = Field(min_length=1, max_length=30)


class ValuationRequest(Model):
    company: str = Field(default='', max_length=100)
    hypothesis: str = Field(default='', max_length=3000)
    valuation_date: date
    currency: Literal['USD', 'CAD', 'EUR', 'GBP'] = 'USD'
    units: Literal['units', 'thousands', 'millions', 'billions'] = 'millions'
    shares: Positive
    current_price: Positive | None = None
    cash: Nonnegative
    debt: Nonnegative
    preferred: Nonnegative
    minority: Nonnegative
    nonoperating: Nonnegative
    tax_benefit: bool = False
    terminal_method: Literal['growth', 'multiple', 'both'] = 'growth'
    cases: list[DCFCase] = Field(default_factory=list, max_length=3)
    comps: Comps | None = None

    @model_validator(mode='after')
    def unique_inputs(self):
        names = [c.name for c in self.cases]
        if len(names) != len(set(names)):
            raise ValueError('Each DCF case may appear only once.')
        if self.cases and 'Base' not in names:
            raise ValueError('Include a Base case when using DCF.')
        if self.cases and len({len(c.years) for c in self.cases}) > 1:
            raise ValueError('Use the same forecast horizon for every DCF case.')
        if not self.cases and self.comps is None:
            raise ValueError('Enable DCF or comparable-company valuation.')
        if self.comps:
            names = [p.name.strip().casefold() for p in self.comps.peers]
            if not self.comps.period.strip() or any(not n for n in names) or len(names) != len(set(names)):
                raise ValueError('Enter a comparison period and unique, nonblank peer names.')
        return self


def bridge(req):
    return req.cash + req.nonoperating - req.debt - req.preferred - req.minority


def quantile(values, fraction):
    """Linear interpolation at (n-1)*q, matching inclusive spreadsheet percentiles."""
    ordered = sorted(values)
    position = D(len(ordered)-1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered)-1)
    return ordered[low] + (ordered[high]-ordered[low]) * (position-low)


def dcf(req, case, method, wacc=None, terminal=None):
    wacc = case.wacc if wacc is None else wacc
    if wacc <= 0:
        raise PortfolioError(f'{case.name}: WACC must be positive.')
    discount = 1 + wacc / 100
    rows = []
    for t, year in enumerate(case.years, 1):
        taxes = (year.ebit if req.tax_benefit else max(D(0), year.ebit)) * year.tax_rate / 100
        nopat = year.ebit - taxes
        fcff = nopat + year.depreciation - year.capex - year.change_nwc
        factor = discount ** -t
        rows.append(dict(year=t, **year.model_dump(), taxes=taxes, nopat=nopat,
                         ebitda=year.ebit+year.depreciation, fcff=fcff,
                         discount_factor=factor, pv_fcff=fcff*factor))
    final = rows[-1]
    if method == 'growth':
        growth = case.growth if terminal is None else terminal
        if growth is None or growth >= wacc or growth <= -100:
            raise PortfolioError(f'{case.name}: enter terminal growth below WACC and above −100%.')
        if final['fcff'] <= 0:
            raise PortfolioError(f'{case.name}: perpetual growth requires positive final-year FCFF. Normalize the final year or use an exit multiple.')
        tv = final['fcff'] * (1 + growth/100) / ((wacc-growth)/100)
    else:
        multiple = case.exit_multiple if terminal is None else terminal
        if multiple is None or multiple <= 0 or final['ebitda'] <= 0:
            raise PortfolioError(f'{case.name}: exit valuation needs a positive EV/EBITDA multiple and positive final-year EBITDA.')
        tv = final['ebitda'] * multiple
    pv_forecast = sum((r['pv_fcff'] for r in rows), D(0))
    pv_terminal = tv / discount ** len(rows)
    ev = pv_forecast + pv_terminal
    equity = ev + bridge(req)
    price = equity / req.shares  # Amounts AND shares use the same selected scale.
    return dict(case=case.name, method=method, wacc=wacc, growth=case.growth,
                exit_multiple=case.exit_multiple, forecast=rows, terminal_value=tv,
                pv_terminal=pv_terminal, pv_forecast=pv_forecast, enterprise_value=ev,
                equity_value=equity, price=price,
                terminal_weight_percent=pv_terminal/ev*100 if ev > 0 else None,
                upside_percent=(price/req.current_price-1)*100 if req.current_price else None)


def comparable_values(req):
    if req.comps is None:
        return [], [], []
    c = req.comps
    definitions = [('EV / EBITDA', 'enterprise_value', 'ebitda'),
                   ('EV / Revenue', 'enterprise_value', 'revenue'),
                   ('P / E', 'equity_value', 'net_income')]
    results, audit, warnings = [], [], []
    for label, numerator, denominator in definitions:
        multiples = []
        for peer in c.peers:
            top, bottom = getattr(peer, numerator), getattr(peer, denominator)
            reason = 'Missing input' if top is None or bottom is None else 'Nonpositive value or denominator' if top <= 0 or bottom <= 0 else None
            multiple = top/bottom if reason is None else None
            audit.append(dict(peer=peer.name, method=label, multiple=multiple, exclusion=reason))
            if multiple is not None:
                multiples.append(multiple)
        target = getattr(c, denominator)
        if target is None or target <= 0:
            warnings.append(f'{label}: enter a positive target {denominator.replace("_", " ")} to estimate value.')
            continue
        if len(multiples) < 2:
            warnings.append(f'{label}: at least two eligible peers are needed; {len(multiples)} available.')
            continue
        qs = [quantile(multiples, q) for q in [D('.25'), D('.5'), D('.75')]]
        # P/E yields common equity directly: never subtract debt a second time.
        equities = [q*target + (bridge(req) if numerator == 'enterprise_value' else 0) for q in qs]
        results.append(dict(method=label, count=len(multiples), multiples=qs,
                            low=equities[0]/req.shares, mid=equities[1]/req.shares, high=equities[2]/req.shares,
                            equity_values=equities, basis='Peer 25th–75th percentiles; marker is median'))
        if len(multiples) < 5:
            warnings.append(f'{label}: only {len(multiples)} eligible peers; this range is sensitive to peer selection.')
    return results, audit, warnings


def sensitivity(req, case, method):
    center = case.growth if method == 'growth' else case.exit_multiple
    step = D('.5') if method == 'growth' else D(1)
    columns = [center + i*step for i in [-2, -1, 0, 1, 2]]
    rows = []
    for shift in [-2, -1, 0, 1, 2]:
        wacc = case.wacc + D(shift)*D('.5')
        values = []
        for terminal in columns:
            try:
                values.append(dcf(req, case, method, wacc, terminal)['price'])
            except PortfolioError:
                values.append(None)
        rows.append(dict(wacc=wacc, values=values))
    return dict(method=method, columns=columns, rows=rows)


def serialize(value):
    if isinstance(value, D):
        return float(value)
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize(v) for v in value]
    return value


def analyze_valuation(req):
    with localcontext() as ctx:
        ctx.prec = 34
        methods = ['growth', 'multiple'] if req.terminal_method == 'both' else [req.terminal_method]
        dcfs = [dcf(req, case, method) for method in methods for case in req.cases]
        comps, audit, warnings = comparable_values(req)
        ranges = []
        sensitivities = []
        for method in methods:
            subset = [r for r in dcfs if r['method'] == method]
            if not subset:
                continue
            base = next(r for r in subset if r['case'] == 'Base')
            prices = [r['price'] for r in subset]
            ranges.append(dict(method='DCF · '+('perpetual growth' if method == 'growth' else 'exit EV/EBITDA'),
                               low=min(prices), mid=base['price'], high=max(prices),
                               basis=f'{len(prices)} entered case(s); marker is Base'))
            sensitivities.append(sensitivity(req, next(c for c in req.cases if c.name == 'Base'), method))
            for r in subset:
                if r['terminal_weight_percent'] is not None and r['terminal_weight_percent'] > 75:
                    warnings.append(f'{r["case"]} / {method}: over 75% of enterprise value comes from terminal value.')
                if r['price'] < 0:
                    warnings.append(f'{r["case"]} / {method}: the equity bridge is negative; this is a funding shortfall, not a tradable negative stock price.')
            named = {r['case']: r['price'] for r in subset}
            if ('Bear' in named and named['Bear'] > named['Base']) or ('Bull' in named and named['Bull'] < named['Base']):
                warnings.append(f'{method}: case values do not follow Bear ≤ Base ≤ Bull; review your assumptions.')
        for r in comps:
            ranges.append({k: r[k] for k in ['method', 'low', 'mid', 'high', 'basis']})
            if r['low'] < 0:
                warnings.append(f'{r["method"]}: the enterprise-to-equity bridge gives a negative equity estimate for part of the range.')
        if not ranges:
            raise PortfolioError('No valuation could be calculated. '+ ' '.join(warnings))
        return serialize(dict(company=req.company, currency=req.currency, units=req.units,
            valuation_date=req.valuation_date.isoformat(), current_price=req.current_price,
            bridge=dict(cash=req.cash, nonoperating=req.nonoperating, debt=req.debt,
                        preferred=req.preferred, minority=req.minority, adjustment=bridge(req), shares=req.shares),
            dcf=dcfs, comps=comps, peer_audit=audit, ranges=ranges, sensitivity=sensitivities,
            warnings=list(dict.fromkeys(warnings)), model_version=1))
