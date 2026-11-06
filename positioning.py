"""Evidence-aware editorial policy, additive to the existing article schema."""
import json
import re
from pathlib import Path
from datetime import datetime, timezone

POLICY = json.loads((Path(__file__).parent / 'editorial_policy.json').read_text(encoding='utf-8'))
COLUMN_MAP = {'project':'opportunity','information':'opportunity','method':'methods','tool':'methods','ai_tool':'methods'}
BUSINESS_FIELDS = ('target_need','product_service','payment_model','acquisition','inputs','limitations','first_test')


def editorial_score(data):
    """Require every bounded component; a model's headline score is not evidence."""
    parts = data.get('score_breakdown')
    if not isinstance(parts, dict):
        raise ValueError('Missing editorial score breakdown')
    for key, maximum in POLICY['weights'].items():
        if type(parts.get(key)) is not int or not 0 <= parts[key] <= maximum:
            raise ValueError('Invalid editorial score component: ' + key)
    return sum(parts[k] for k in POLICY['weights'])


def upgrade(row, ai=None, article=None):
    """Never promote AI-created experiments or change original IDs/URLs."""
    ai, article = ai or {}, article or {}
    column = ai.get('column') or row.get('column') or COLUMN_MAP.get(row.get('discovery_category'))
    if column not in POLICY['columns'] or column == 'experiments':
        # Only an explicit owner record can become a project experiment.
        column = 'experiments' if row.get('owner_confirmed') is True and row.get('experiment_record') else COLUMN_MAP.get(row.get('discovery_category'),'opportunity')
    if row.get('section') != 'discovery':
        column = 'archive'
    row.update(schema_version=3, column=column)
    tags = ai.get('topics', row.get('topics', []))
    if not isinstance(tags,list):
        tags = []
    row['topics'] = list(dict.fromkeys(t for t in tags if t in POLICY['topics']))[:5]
    row['source_published_at'] = row.get('source_published_at', article.get('published_at',row.get('published_at')))
    row['collected_at'] = row.get('collected_at') or (datetime.now(timezone.utc).isoformat() if article else None)
    row['source_evidence_type']=article.get('source_evidence_type',row.get('source_evidence_type','unknown'))
    row['evidence_status'] = 'author_reported_unverified' if row['source_evidence_type']=='author_self_report' else 'public_source_unverified'
    if row.get('income_claim_status') == 'unverified':
        row['evidence_status'] = 'author_reported_unverified'
    if row.get('publication_basis') == 'editorial_source_review':
        row['evidence_status'] = 'public_documentation_only'
    detail = ai.get('business_details',row.get('business_details',{}))
    row['business_details'] = {k:str(detail.get(k) or '未披露')[:600] for k in BUSINESS_FIELDS} if isinstance(detail,dict) else {}
    claims = ai.get('income_claims', [])
    row['income_claims'] = []
    for claim in claims[:8] if isinstance(claims,list) else []:
        if not isinstance(claim,dict):
            continue
        # An explicitly quoted platform fee/price is a cost, not earned revenue.
        quote=str(claim.get('source_quote') or '')
        source_body=re.sub(r'\s+',' ',str(article.get('body','')))
        if (quote and re.sub(r'\s+',' ',quote) in source_body
                and re.search(r'平台服务费|手续费|店铺月租|订阅价格|platform fee|transaction fee',quote,re.I)
                and not re.search(r'收入|收益|盈利|利润|赚|营收|revenue|profit|earned|income',quote,re.I)):
            row.setdefault('cost_source_quotes',[]).append(quote[:400])
            continue
        row['income_claims'].append({k:str(claim.get(k) or '未披露')[:400] for k in ('metric','amount','period','attribution','source_quote')})
        row['income_claims'][-1]['attribution']='作者自述（未经独立核验）'
    if row['income_claims']:
        row['evidence_status']='author_reported_unverified'
        row['income_claim_status']='unverified'
        row['review_status']='pending'
    if ai:
        row['score_breakdown']=ai.get('score_breakdown',{})
        row['score_type']='editorial_ranking'
    return row
