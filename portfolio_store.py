"""Named portfolio snapshots stored locally, with atomic optimistic updates."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import unicodedata
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
from analytics_store import AnalyticsDraft
from backtest_store import BacktestDraft
from covered_call_store import CoveredCallDraft
from research_store import SurfaceDraft, CryptoDraft


class DraftModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Security(DraftModel):
    ticker: str = Field(min_length=1, max_length=40)
    name: str = Field(default='', max_length=500)
    exchange: str = Field(default='', max_length=100)
    currency: str = Field(default='USD', max_length=10)


class HoldingDraft(Security):
    # Preserve incomplete input verbatim; financial validation happens on Analyze.
    qty: str = Field(default='', max_length=100)
    avg_cost: str = Field(default='', max_length=100)
    percent: str = Field(default='0', max_length=100)
    dollars: str = Field(default='0', max_length=100)
    purchase_price: str = Field(default='', max_length=100)


class SettingsDraft(DraftModel):
    benchmark: str = Field(default='SPY', max_length=40)
    period: Literal['6mo','1y','2y','5y','max'] = '1y'
    interval: Literal['1d','1wk','1mo'] = '1d'
    window: str = Field(default='30', max_length=100)
    return_basis: Literal['price','total'] = 'price'
    risk_free_percent: str = Field(default='0', max_length=100)


class CsvPosition(DraftModel):
    ticker: str = Field(min_length=1, max_length=40)
    qty: float = Field(gt=0)
    avg_cost: float = Field(ge=0)
    currency: Literal['USD'] = 'USD'


class CsvDraft(DraftModel):
    name: str = Field(max_length=255)
    positions: list[CsvPosition] = Field(max_length=200)


class OptionLegDraft(DraftModel):
    kind: Literal['call','put','stock'] = 'call'
    side: Literal['buy','sell'] = 'buy'
    quantity: str = Field(default='1',max_length=100)
    multiplier: str = Field(default='100',max_length=100)
    strike: str = Field(default='',max_length=100)
    premium: str = Field(default='',max_length=100)
    expiration: str = Field(default='',max_length=100)
    iv: str = Field(default='',max_length=100)
    contract_symbol: str = Field(default='',max_length=100)
    quote_note: str = Field(default='',max_length=500)


class FinderDraft(DraftModel):
    target_price: str = Field(default='',max_length=100)
    target_date: str = Field(default='',max_length=100)
    max_risk: str = Field(default='',max_length=100)
    min_open_interest: str = Field(default='0',max_length=100)
    pricing: Literal['natural','mid'] = 'natural'
    rank: Literal['pnl','return'] = 'pnl'
    option_type: Literal['both','call','put'] = 'both'
    types: list[Literal['long','short','debit_spread','credit_spread']] = Field(default_factory=lambda:['long'],max_length=4)
    expirations: list[str] = Field(default_factory=list,max_length=4)


class OptionsSetupDraft(DraftModel):
    exposure_multiplier: Literal['1','2','3','5'] = '1'
    strategy: str = Field(default='long_call',max_length=80)
    symbol: str = Field(default='',max_length=40)
    valuation_mode: Literal['expiry','dated'] = 'expiry'
    currency: Literal['USD','CAD'] = 'USD'
    spot: str = Field(default='',max_length=100)
    as_of: str = Field(default='',max_length=100)
    target_date: str = Field(default='',max_length=100)
    rate: str = Field(default='0',max_length=100)
    dividend_yield: str = Field(default='0',max_length=100)
    iv_shift: str = Field(default='0',max_length=100)
    probability_iv: str = Field(default='30',max_length=100)
    fee_per_contract: str = Field(default='0',max_length=100)
    capital_basis: str = Field(default='',max_length=100)
    comparison_budget: str = Field(default='',max_length=100)
    financing_enabled: bool = False
    borrowed_amount: str = Field(default='0',max_length=100)
    borrowing_rate: str = Field(default='0',max_length=100)
    financing_days: str = Field(default='',max_length=100)
    include_stock_cost: bool = True
    show_stock: bool = False
    output: Literal['pnl','return_percent','position_value'] = 'pnl'
    result_view: Literal['heatmap','line','table'] = 'heatmap'
    scenario_name: str = Field(default='',max_length=80)
    range_min: str = Field(default='',max_length=100)
    range_max: str = Field(default='',max_length=100)
    scenario_price: str = Field(default='',max_length=100)
    legs: list[OptionLegDraft] = Field(default_factory=list,max_length=9)


class OptionsPreset(DraftModel):
    id: str = Field(max_length=100)
    name: str = Field(min_length=1,max_length=80)
    state: OptionsSetupDraft


class OptionsDraft(OptionsSetupDraft):
    # Version 1 fields stay readable so old snapshots can be migrated in the UI.
    engine_version: Literal[1,2,3,4] = 1
    expiration: str = Field(default='',max_length=100)
    contracts: str = Field(default='1',max_length=100)
    multiplier: str = Field(default='100',max_length=100)
    strike: str = Field(default='',max_length=100)
    premium: str = Field(default='',max_length=100)
    stock_entry: str = Field(default='',max_length=100)
    option_type: Literal['call','put'] = 'call'
    long_strike: str = Field(default='',max_length=100)
    long_premium: str = Field(default='',max_length=100)
    short_strike: str = Field(default='',max_length=100)
    short_premium: str = Field(default='',max_length=100)
    range_min: str = Field(default='0',max_length=100)
    finder: FinderDraft = Field(default_factory=FinderDraft)
    scenarios: list[OptionsPreset] = Field(default_factory=list,max_length=12)


class WorkspaceState(DraftModel):
    schema_version: Literal[1] = 1
    mode: Literal['holdings','research'] = 'holdings'
    source: Literal['quantity','allocation','csv'] = 'quantity'
    view: Literal['overview','holdings','research','options','analytics','backtesting','risk','settings','volatility','crypto'] = 'overview'
    holdings: list[HoldingDraft] = Field(default_factory=list, max_length=200)
    research: list[Security] = Field(default_factory=list, max_length=200)
    cash: str = Field(default='0', max_length=100)
    budget: str = Field(default='10000', max_length=100)
    unit: Literal['percent','dollars'] = 'percent'
    settings: SettingsDraft = Field(default_factory=SettingsDraft)
    csv: CsvDraft | None = None
    options: OptionsDraft = Field(default_factory=OptionsDraft)
    analytics: AnalyticsDraft = Field(default_factory=AnalyticsDraft)
    backtest: BacktestDraft = Field(default_factory=BacktestDraft)
    backtest_tool: Literal['stocks','covered_call'] = 'stocks'
    covered_call: CoveredCallDraft = Field(default_factory=CoveredCallDraft)
    volatility: SurfaceDraft = Field(default_factory=SurfaceDraft)
    crypto: CryptoDraft = Field(default_factory=CryptoDraft)


class SavePortfolio(DraftModel):
    id: UUID
    name: str = Field(min_length=1, max_length=80)
    revision: int = Field(ge=0)
    state: WorkspaceState

    @field_validator('name')
    @classmethod
    def normalize_name(cls, value):
        name = unicodedata.normalize('NFC', value).strip()
        if not name or any(unicodedata.category(c).startswith('C') for c in name):
            raise ValueError('Use a name with visible characters and no control characters.')
        return name


class StoreError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class PortfolioStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA busy_timeout = 10000')
            connection.execute('''CREATE TABLE IF NOT EXISTS portfolios (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                name_key TEXT NOT NULL UNIQUE,
                state_json TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )''')
            connection.commit()
            os.chmod(self.path, 0o600)
        except Exception:
            connection.close()
            raise
        return connection

    @staticmethod
    def document(row):
        record = {k: row[k] for k in ['id','name','revision','created_at','updated_at']}
        if 'state_json' in row.keys():
            # Refuse damaged/unsupported data without silently replacing it.
            try:
                record['state'] = WorkspaceState.model_validate_json(row['state_json']).model_dump()
            except ValueError as exc:
                raise StoreError('This saved portfolio could not be read. Your stored data has been kept.', 500) from exc
        return record

    def list(self):
        try:
            with closing(self.connect()) as db:
                rows = db.execute('SELECT id, name, revision, created_at, updated_at FROM portfolios ORDER BY name_key').fetchall()
                return [self.document(row) for row in rows]
        except (sqlite3.Error, OSError) as exc:
            raise StoreError('Saved portfolios are unavailable. Your current edits have been kept; retry when local storage is available.') from exc

    def get(self, portfolio_id):
        try:
            with closing(self.connect()) as db:
                row = db.execute('SELECT * FROM portfolios WHERE id = ?', (str(portfolio_id),)).fetchone()
                if row is None:
                    raise StoreError('That saved portfolio is no longer available.', 404)
                return self.document(row)
        except (sqlite3.Error, OSError) as exc:
            raise StoreError('Cannot load this portfolio right now. Your current edits have been kept.') from exc

    def save(self, request):
        portfolio_id, name = str(request.id), request.name
        serialized = json.dumps(request.state.model_dump(), sort_keys=True, ensure_ascii=False, allow_nan=False)
        now = datetime.now(timezone.utc).isoformat()
        try:
            with closing(self.connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM portfolios WHERE id = ?', (portfolio_id,)).fetchone()
                old_serialized = None
                if old:
                    old_state = self.document(old)['state']
                    old_serialized = json.dumps(old_state, sort_keys=True, ensure_ascii=False, allow_nan=False)
                    if 'options' in request.state.model_fields_set and request.state.options.engine_version < old_state['options']['engine_version']:
                        raise StoreError('This page uses an older Options Lab. Refresh before saving, or save a copy to keep both workspaces.', 409)
                    if 'analytics' in request.state.model_fields_set and request.state.analytics.version < old_state['analytics']['version']:
                        raise StoreError('This page uses an older Analytics Lab. Refresh before saving, or save a copy to keep both workspaces.', 409)
                    # Open older pages must not erase lab inputs they do not know.
                    state = request.state.model_dump()
                    for lab in ['options', 'analytics', 'backtest', 'backtest_tool', 'covered_call', 'volatility', 'crypto']:
                        if lab not in request.state.model_fields_set:
                            state[lab] = old_state[lab]
                    serialized = json.dumps(state,sort_keys=True,ensure_ascii=False,allow_nan=False)
                if old and old['name'] == name and old_serialized == serialized:
                    # A successful save whose response was lost can be retried safely.
                    return self.document(old)
                if (old and old['revision'] != request.revision) or (not old and request.revision != 0):
                    raise StoreError('This portfolio was changed elsewhere. Your edits are kept. Save a copy to preserve both versions.', 409)
                if old:
                    db.execute('''UPDATE portfolios SET name = ?, name_key = ?, state_json = ?,
                                  revision = revision + 1, updated_at = ? WHERE id = ?''',
                               (name, name.casefold(), serialized, now, portfolio_id))
                else:
                    db.execute('''INSERT INTO portfolios (id, name, name_key, state_json, revision, created_at, updated_at)
                                  VALUES (?, ?, ?, ?, 1, ?, ?)''',
                               (portfolio_id, name, name.casefold(), serialized, now, now))
                return self.document(db.execute('SELECT * FROM portfolios WHERE id = ?', (portfolio_id,)).fetchone())
        except sqlite3.IntegrityError as exc:
            raise StoreError('A portfolio with that name already exists. Choose another name or load the existing portfolio.', 409) from exc
        except (sqlite3.Error, OSError) as exc:
            raise StoreError('The portfolio could not be saved to your device. Your edits are kept; try Save again.', 503) from exc


store = PortfolioStore(Path(__file__).parent / 'data' / 'portfolios.sqlite3')
