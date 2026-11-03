"""Incremental discovery schema; verification is editorial, never inferred by AI."""
import re
import json

CATEGORIES={'project':'赚钱项目','method':'赚钱方法','tool':'实用工具','ai_tool':'AI工具','information':'信息差'}
CLAIMS=re.compile(r'稳赚|保本|保收益|零风险|躺赚|包赚|保证.{0,8}(收入|收益|盈利)|[日月年]入|(?:收入|收益|盈利|赚到|赚取).{0,12}[0-9一二三四五六七八九十百千万亿]|[0-9]+\s*(?:元|万元|美元).{0,8}(?:收入|收益|利润)',re.I)


def apply_schema(row, ai, article):
    category=ai.get('discovery_category')
    discovery=ai.get('discovery_relevant') is True and category in CATEGORIES
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
    return row
