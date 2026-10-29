// In-site Chinese editorial reader. Source articles remain linked, not reproduced verbatim.
let articleBodies={},lastReadingView="featured",lastReadingScroll=0,currentArticleId="";
const articleEndpoint=/^(localhost|127\.0\.0\.1)$/.test(location.hostname)?"/api/article-bodies":"articles.json";
const bodyRequest=fetch(articleEndpoint,{cache:"no-cache"}).then(r=>{if(!r.ok)throw Error("Article data unavailable");return r.json()}).catch(()=>fetch("articles.json",{cache:"no-cache"}).then(r=>r.ok?r.json():{articles:{}})).then(j=>{articleBodies=j.articles||{}}).catch(()=>{});
function openArticle(id,fromHistory=false){const item=publicItems.find(x=>x.id===id);if(!item)return false;
 if(!$("#article").classList.contains("active")){lastReadingView=document.querySelector(".view.active")?.id||"featured";lastReadingScroll=window.scrollY}
 currentArticleId=id;
 $("#articleSource").textContent=item.source;
 $("#articleDate").textContent=`发布：${dayOf(item)} · 来源原文可核查`;
 $("#articleCategory").textContent=item.category;
 $("#articleTitle").textContent=item.title;
 $("#articleDeck").textContent=item.summary;
 const aiAssisted=item.reviewStatus==="approved";
 $("#articleByline").textContent=`${aiAssisted?"AI 辅助整理 · 自动审核通过":"AIBEEP 编辑整理"}　·　${dayOf(item)}`;
 $("#articleDisclosure").textContent=aiAssisted?"本文由 AIBEEP 基于公开官方资料进行 AI 辅助中文整理，并通过独立自动审核；不代表来源机构立场，具体事实以原文为准。":"本文为 AIBEEP 根据公开官方资料编写的中文整理与解读，不是原文全文翻译。";
 const details=articleBodies[id],sections=details?.sections?.length?details.sections:[{title:"核心信息",paragraphs:[item.summary]},{title:"为什么值得关注",paragraphs:["这项更新与广告投放、营销策略或企业增长有关。具体适用条件和后续产品变化请查看文末官方原始来源，避免把单条公告直接理解为所有账户的通用规则。"]}];
 $("#articleIntro").textContent=details?.intro||item.summary;
 $("#articleToc").innerHTML=sections.map((s,i)=>`<a href="#reading-${i}" data-toc="${i}">${esc(s.title)}</a>`).join("");
 $("#articleBody").innerHTML=sections.map((s,i)=>`<section class="article-section" id="reading-${i}"><h2>${esc(s.title)}</h2>${(s.paragraphs||[]).map(p=>`<p>${esc(p)}</p>`).join("")}</section>`).join("");
 $("#articleTopics").innerHTML=`<span class="article-topic">${esc(item.category)}</span><span class="article-topic">${esc(item.source)}</span>`;
 $("#articleOriginal").href=item.url;$("#articleOriginalBottom").href=item.url;
 $("#articleSave").textContent=isBookmarked(id)?"★ 已收藏":"☆ 收藏本文";
 go("article");if(!fromHistory)history.pushState({aibeepArticle:id},"",`#article/${encodeURIComponent(id)}`);return true}
function closeArticle(){const target=lastReadingView==="article"?"featured":lastReadingView;currentArticleId="";go(target);history.replaceState({},"",location.pathname+location.search);window.scrollTo(0,lastReadingScroll)}
$("#articleBack").onclick=closeArticle;$$("[data-article-back]").forEach(b=>b.onclick=closeArticle);
$("#articleSave").onclick=()=>{if(!currentArticleId)return;const ids=new Set(bookmarkIds());ids.has(currentArticleId)?ids.delete(currentArticleId):ids.add(currentArticleId);localStorage.setItem(BOOKMARKS_KEY,JSON.stringify([...ids]));$("#articleSave").textContent=ids.has(currentArticleId)?"★ 已收藏":"☆ 收藏本文";toast(ids.has(currentArticleId)?"已收藏文章":"已取消收藏");renderEditorial()};
document.addEventListener("click",event=>{const toc=event.target.closest("[data-toc]");if(toc){event.preventDefault();$("#reading-"+toc.dataset.toc)?.scrollIntoView({behavior:"smooth",block:"start"});return}
 if(event.target.closest("#article")||event.target.closest("button,[data-bookmark],.theme-card"))return;
 const story=event.target.closest(".timeline-entry,.spotlight-card,.hot-main,.hot-minicard,.rank-row,.digest-article");if(!story)return;
 const directLink=event.target.closest("a[href]");let item;
 if(directLink)item=publicItems.find(x=>x.url===directLink.href);
 if(!item){const originalLink=story.querySelector("a[href]");if(originalLink)item=publicItems.find(x=>x.url===originalLink.href)}
 if(!item){const heading=story.querySelector("h2,h3,strong");if(heading)item=publicItems.find(x=>x.title===heading.textContent)}
 if(item){event.preventDefault();bodyRequest.then(()=>openArticle(item.id))}
});
function restoreArticleFromUrl(){const m=location.hash.match(/^#article\/(.+)$/);if(!m)return;const id=decodeURIComponent(m[1]);Promise.resolve(bodyRequest).then(()=>openArticle(id,true))}
window.addEventListener("aibeep:content",restoreArticleFromUrl);
window.addEventListener("popstate",()=>{if(location.hash.startsWith("#article/")){restoreArticleFromUrl()}else if($("#article").classList.contains("active")){go(lastReadingView)}});
bodyRequest.then(restoreArticleFromUrl);
