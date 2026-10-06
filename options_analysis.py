"""Vanilla-option strategy P&L at expiration. No live quotes or option pricing.

Use exact decimal arithmetic for piecewise-linear roots, extrema and premiums.
Extrema cover S >= 0, independently of the requested chart window.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import math

from tracker import PortfolioError

STRATEGIES = {'long_call':'Long call', 'long_put':'Long put', 'covered_call':'Covered call',
              'protective_put':'Protective put', 'vertical':'Vertical spread'}


def number(data, key, label, minimum=0, positive=False, integer=False, default=None):
    value = data.get(key, default)
    try:
        if isinstance(value, bool) or value is None or str(value).strip() == '':
            raise InvalidOperation
        value = Decimal(str(value))
        if not value.is_finite() or value < minimum or (positive and value == 0):
            raise InvalidOperation
        if integer and value != value.to_integral_value():
            raise InvalidOperation
        if value > Decimal('1e12'):
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        kind = 'positive whole number' if integer else 'positive number' if positive else 'non-negative number'
        raise PortfolioError(f'{label} must be a finite {kind}, no greater than 1 trillion.') from None
    return value


def _zeros(knots, evaluate, tail_slope):
    points, intervals = set(), []
    for a, b in zip(knots, knots[1:]):
        fa, fb = evaluate(a), evaluate(b)
        if fa == fb == 0:
            intervals.append([a,b])
        else:
            if fa == 0: points.add(a)
            if fb == 0: points.add(b)
            if fa * fb < 0: points.add(a - fa * (b-a) / (fb-fa))
    end, value = knots[-1], evaluate(knots[-1])
    if tail_slope == 0:
        if value == 0: intervals.append([end,None])
    else:
        root = end - value / tail_slope
        if root >= end: points.add(root)
    merged = []
    for a,b in intervals:
        if merged and merged[-1][1] is not None and a <= merged[-1][1]:
            merged[-1][1] = b
        else:
            merged.append([a,b])
    points = sorted(p for p in points if not any(p >= a and (b is None or p <= b) for a,b in merged))
    return points, merged


def analyze_options(data):
    with localcontext() as ctx:
        ctx.prec = 50
        return _analyze(data)


def _analyze(data):
    strategy = data.get('strategy')
    if strategy not in STRATEGIES:
        raise PortfolioError('Choose a supported options strategy.')
    symbol = str(data.get('symbol','')).strip().upper()
    if len(symbol) > 40:
        raise PortfolioError('Use an underlying label of at most 40 characters.')
    expiration = data.get('expiration') or None
    if expiration:
        try: expiration = date.fromisoformat(expiration).isoformat()
        except (ValueError, TypeError): raise PortfolioError('Use a valid expiration date.') from None
    contracts = number(data, 'contracts', 'Contracts', positive=True, integer=True, default=1)
    multiplier = number(data, 'multiplier', 'Contract size', positive=True, integer=True, default=100)
    units = contracts * multiplier
    stock_units = units if strategy in {'covered_call','protective_put'} else Decimal(0)
    stock_entry = number(data, 'stock_entry', 'Share purchase price') if stock_units else Decimal(0)
    legs = []
    def leg(side, kind, strike_key, premium_key, description):
        legs.append({'side':side,'kind':kind,
                     'strike':number(data,strike_key,description+' strike',positive=True),
                     'premium':number(data,premium_key,description+' premium')})
    if strategy == 'vertical':
        kind = data.get('option_type','call')
        if kind not in {'call','put'}: raise PortfolioError('Choose calls or puts for a vertical spread.')
        leg(1,kind,'long_strike','long_premium','Long leg')
        leg(-1,kind,'short_strike','short_premium','Short leg')
        if legs[0]['strike'] == legs[1]['strike']:
            raise PortfolioError('A vertical spread needs two different strikes with the same expiration and contract size.')
        bull = legs[0]['strike'] < legs[1]['strike']
        name = ('Bull ' if bull else 'Bear ') + kind + ' spread'
    else:
        kind = 'put' if strategy in {'long_put','protective_put'} else 'call'
        leg(-1 if strategy=='covered_call' else 1,kind,'strike','premium','Option')
        name = STRATEGIES[strategy]
    def option_pnl(leg, spot):
        intrinsic = max(Decimal(0), spot-leg['strike'] if leg['kind']=='call' else leg['strike']-spot)
        return leg['side'] * units * (intrinsic-leg['premium'])
    def pnl(spot):
        return stock_units*(spot-stock_entry) + sum((option_pnl(leg,spot) for leg in legs),Decimal(0))
    knots = sorted({Decimal(0),*[leg['strike'] for leg in legs]})
    tail_slope = stock_units + sum((leg['side']*units for leg in legs if leg['kind']=='call'),Decimal(0))
    values = [pnl(k) for k in knots]
    minimum, maximum = min(values), max(values)
    loss_unlimited, profit_unlimited = tail_slope < 0, tail_slope > 0
    roots, ranges = _zeros(knots,pnl,tail_slope)
    warnings = []
    if not profit_unlimited and maximum < 0:
        warnings.append('These inputs produce a loss at every possible expiration price. Check the entered premiums and share cost.')
    if not loss_unlimited and minimum > 0:
        warnings.append('These inputs produce a profit at every possible expiration price in this model. Verify the manual prices; this does not establish a tradable opportunity.')
    if strategy=='vertical':
        net = legs[0]['premium'] - legs[1]['premium']
        width = abs(legs[0]['strike']-legs[1]['strike'])
        intrinsic_change = pnl(knots[-1])-pnl(Decimal(0))
        usual_debit = (kind=='call' and intrinsic_change>0) or (kind=='put' and intrinsic_change<0)
        if abs(net)>width or (usual_debit and net<0) or (not usual_debit and net>0):
            warnings.append('The entered spread premiums are outside the usual debit/credit relationship. The chart still uses your exact inputs.')
    reference = max([Decimal(1),stock_entry,*[leg['strike'] for leg in legs],*roots])
    low = number(data,'range_min','Chart minimum price',default=0)
    high = number(data,'range_max','Chart maximum price',positive=True) if data.get('range_max') is not None else reference*Decimal('1.5')
    if high <= low: raise PortfolioError('Chart maximum price must be greater than its minimum.')
    scenario = number(data,'scenario_price','Scenario expiration price') if data.get('scenario_price') is not None else legs[0]['strike']
    prices = {low+(high-low)*Decimal(i)/200 for i in range(201)}
    prices.update(k for k in [*knots,*roots,scenario] if low<=k<=high)
    chart = [{'price':float(s),'pnl':float(pnl(s))} for s in sorted(prices)]
    option_debit = sum((leg['side']*units*leg['premium'] for leg in legs),Decimal(0))
    stock_cost = stock_units*stock_entry
    detail=[]
    if stock_units:
        detail.append({'label':'Long shares','quantity':int(stock_units),'unit':'shares',
                       'entry_price':float(stock_entry),'strike':None,'initial_cash_flow':float(-stock_cost),
                       'expiration_value':float(stock_units*scenario),'pnl':float(stock_units*(scenario-stock_entry))})
    for leg in legs:
        initial = -leg['side']*units*leg['premium']
        detail.append({'label':('Buy ' if leg['side']>0 else 'Sell ')+leg['kind'],
                       'quantity':int(contracts),'unit':'contracts','entry_price':float(leg['premium']),
                       'strike':float(leg['strike']),'initial_cash_flow':float(initial),
                       'expiration_value':float(option_pnl(leg,scenario)-initial),'pnl':float(option_pnl(leg,scenario))})
    result = {'strategy':strategy,'strategy_name':name,'symbol':symbol,'expiration':expiration,
              'contracts':int(contracts),'multiplier':int(multiplier),'stock_quantity':int(stock_units),
              'net_option_debit':float(option_debit),'stock_cost':float(stock_cost),'net_initial_debit':float(option_debit+stock_cost),
              'maximum_profit':None if profit_unlimited else float(max(Decimal(0),maximum)),
              'maximum_loss':None if loss_unlimited else float(max(Decimal(0),-minimum)),
              'profit_unlimited':profit_unlimited,'loss_unlimited':loss_unlimited,
              'best_case_pnl':None if profit_unlimited else float(maximum),
              'worst_case_pnl':None if loss_unlimited else float(minimum),
              'break_evens':[float(r) for r in roots],
              'break_even_ranges':[{'from':float(a),'to':float(b) if b is not None else None} for a,b in ranges],
              'chart':chart,'range_min':float(low),'range_max':float(high),'scenario_price':float(scenario),
              'scenario_pnl':float(pnl(scenario)),'legs':detail,'warnings':warnings}
    if not all(math.isfinite(row['pnl']) and math.isfinite(row['price']) for row in chart):
        raise PortfolioError('Values are too large to calculate reliably.')
    return result
