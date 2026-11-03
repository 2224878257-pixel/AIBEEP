"""Incremental discovery schema; verification is editorial, never inferred by AI."""
import re
import json

CATEGORIES={'project':'赚钱项目','method':'赚钱方法','tool':'实用工具','ai_tool':'AI工具','information':'信息差'}
CLAIMS=re.compile(r'稳赚|保本|保收益|零风险|无风险|躺赚|包赚|人人.{0,5}赚|保证.{0,8}(收入|收益|盈利|获利)|[日月年]入|赚.{0,6}[0-9一二三四五六七八九十百千万亿]|已(?:经)?(?:证实|验证).{0,5}盈利|已盈利|实现盈利|(?:收入|收益|盈利|赚到|赚取).{0,12}[0-9一二三四五六七八九十百千万亿]|[0-9]+\s*(?:元|万元|美元).{0,8}(?:收入|收益|利润)',re.I)
CLAIMS=re.compile(CLAIMS.pattern+r'|(?:MRR|ARR|revenue|profit|GMV|funding|income|earned|made|sales).{0,30}(?:[$€£]\s*\d|\d[\d,.]*\s*(?:USD|dollars|k\b|m\b))|[$€£]\s*\d[\d,.]*.{0,20}(?:MRR|ARR|revenue|profit|income)',re.I)


def apply_schema(row, ai, article):
    category=ai.get('discovery_category')
    discovery=ai.get('discovery_relevant') is True and category in CATEGORIES
    title=str(article.get('title',''))
    if category=='information' and re.search(r'投放|投流|获客|广告|营销|品牌总监|聚光|千川',title) and not re.search(r'工具|AI|Copilot|自动化|开源|副业|变现|赚钱|独立开发|SaaS|数字产品',title,re.I):
        discovery=False
    row.update(schema_version=2,section='discovery' if discovery else 'legacy',
               discovery_category=category if discovery else None,
               tested_status='unknown',verification_status='unverified',sponsorship_status='unknown')
    row['detail_kind']='project' if category in {'project','method'} else 'tool' if category in {'tool','ai_tool'} else 'information'
    details=ai.get('discovery_details')
    row['discovery_details']={k:str(details.get(k) or '来源未说明')[:600] for k in ('purpose','audience','requirements','costs','risks','next_step')} if isinstance(details,dict) else {}
    has_claim=bool(CLAIMS.search(' '.join(str(article.get(k,'')) for k in ('title','body'))+' '+json.dumps(ai,ensure_ascii=False)))
    row['income_claim_status']='unverified' if has_claim else 'not_stated'
    # Project/method items and any income promises require a human decision before publication.
    row['review_status']='pending' if discovery and (category in {'project','method'} or has_claim) else 'published'
    if ai.get('column')=='case':
        facts=ai.get('business_details',{})
        if not isinstance(facts,dict) or any(not facts.get(k) or facts[k] in {'未披露','来源未说明'} for k in ('target_need','product_service')):
            row.update(review_status='pending',hold_reason='insufficient_business_process')
    return row
