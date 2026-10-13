'use strict';
let data={stories:[],feeds:[],state:{read:[],saved:{},compact:false},errors:{},loading:true};
const articleCache=new Map();
let view='all', query='', selected=null, visible=[];
const $=id=>document.getElementById(id);
const send=(action,extra={})=>window.webkit?.messageHandlers.reader.postMessage(JSON.stringify({action,...extra}));
const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node};
window.applyTheme=colors=>{for(const [key,value] of Object.entries(colors)){if(/^#[0-9a-f]{6}$/i.test(value)){document.documentElement.style.setProperty('--'+({lighter_background:'panel',bright_foreground:'bright'}[key]||key),value)}}};
window.receive=payload=>{data=payload;window.applyTheme(data.colors);render();if($('feed-dialog').open){$('feed-notice').textContent=data.notice||'';renderManage()}};
function age(story){if(!story.published)return 'Headline link';const hours=Math.max(0,Math.floor((Date.now()/1000-story.published)/3600));return hours<1?'Just in':hours<24?hours+'h ago':Math.floor(hours/24)+'d ago'}
function filtered(){let stories=view==='saved'?Object.values(data.state.saved):data.stories;if(view==='unread')stories=stories.filter(s=>!data.state.read.includes(s.id));else if(!['all','saved'].includes(view))stories=stories.filter(s=>s.feed_id===view);if(query)stories=stories.filter(s=>(s.title+' '+s.source+' '+(s.body||'')).toLowerCase().includes(query));return stories}
function navButton(name,symbol,count,id){const button=el('button',view===id?'active':'');button.append(el('span','symbol',symbol),el('span','name',name),el('span','count',String(count)));button.onclick=()=>{view=id;render()};return button}
function metadata(story){const meta=el('div','meta');if(!data.state.read.includes(story.id))meta.append(el('span','unread-dot'));meta.append(el('span','source',story.source),el('span','','·'),el('span','',age(story)));return meta}
function saveButton(story){const saved=!!data.state.saved[story.id];const button=el('button','save'+(saved?' saved':''),saved?'★':'☆');button.title=saved?'Remove from saved':'Save story';button.setAttribute('aria-label',button.title);button.onclick=()=>send('save',{id:story.id});return button}
function requestArticle(){if(!selected)return;$('article-status').textContent='Loading reader view…';$('article-load').disabled=true;send('article',{id:selected.id})}
window.receiveArticle=result=>{if(result.body)articleCache.set(result.id,result.body);if(selected?.id!==result.id)return;$('article-load').disabled=false;$('article-load').hidden=!!result.body;if(result.body){$('article-body').textContent=result.body;$('article-status').textContent='Reader view · '+Math.max(1,Math.ceil(result.body.split(/\s+/).length/220))+' min read'}else{$('article-status').textContent=result.error||'Reader view unavailable. Feed text is shown.'}};
function openStory(story){selected=story;$('article-title').textContent=story.title;$('article-source').textContent=story.source+' · '+age(story);$('article-body').textContent=articleCache.get(story.id)||story.body||'This source provides a headline link. Loading the article from its publisher…';$('article-status').textContent=articleCache.has(story.id)?'Reader view':'From your feed';$('article-load').hidden=articleCache.has(story.id);$('article-load').disabled=false;$('article-save').textContent=data.state.saved[story.id]?'★ Saved':'☆ Save';if(!$('article-dialog').open)$('article-dialog').showModal();$('article-dialog').scrollTop=0;send('read',{id:story.id});if(!articleCache.has(story.id)&&(story.body||'').length<1500)requestArticle()}
$('article-load').onclick=requestArticle;
function layout(){return data.state.layout|| (data.state.compact?'headlines':'briefing')}
function photo(story){if(!data.state.photos||layout()==='headlines'||!story.image)return null;let url;try{url=new URL(story.image)}catch{return null}if(!['https:','http:'].includes(url.protocol)||url.username||url.password)return null;const img=el('img','story-photo');img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';img.onerror=()=>img.remove();img.src=url.href;return img}
function storyCard(story){const card=el('article','story'+(data.state.read.includes(story.id)?' is-read':''));const button=el('button','headline');button.append(el('h3','',story.title));button.onclick=()=>openStory(story);const bottom=el('div','story-bottom');bottom.append(el('p','summary',(story.body||'Open the headline to read at the original source.').replace(/\s+/g,' ')),saveButton(story));const image=photo(story);if(image)card.append(image);card.append(metadata(story),button,bottom);return card}
function render(){
 document.body.classList.toggle('compact',layout()==='headlines');
 document.body.dataset.layout=layout();
 document.querySelectorAll('[name=layout]').forEach(input=>input.checked=input.value===layout());
 $('photos').checked=!!data.state.photos;
 $('date').textContent=new Date().toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'}).toUpperCase();
 const unread=data.stories.filter(s=>!data.state.read.includes(s.id)).length;
 $('library').replaceChildren(navButton('All stories','◫',data.stories.length,'all'),navButton('Unread','◉',unread,'unread'),navButton('Saved for later','☆',Object.keys(data.state.saved).length,'saved'));
 $('sources').replaceChildren(...data.feeds.map(f=>{const b=navButton(f.name,'',data.stories.filter(s=>s.feed_id===f.id&&!data.state.read.includes(s.id)).length,f.id);b.firstChild.className='source-dot';if(data.errors[f.id]){b.firstChild.style.background='var(--muted)';b.title='Could not refresh · Showing cached stories'}return b}));
 const feed=data.feeds.find(f=>f.id===view);
 const title=view==='all'?'Your briefing':view==='unread'?'Still to read':view==='saved'?'Saved for later':feed?.name||'Your briefing';
 $('heading').replaceChildren(document.createTextNode(title),el('span','','.'));
 $('subtitle').textContent=view==='saved'?'The stories you want to come back to.':view==='unread'?'Catch up at your own pace.':feed?'Headlines and excerpts from '+feed.name+'.':data.feeds.length+' sources. One place to catch up.';
 $('refresh').disabled=data.loading;$('refresh').querySelector('span').textContent=data.loading?'Refreshing…':'Refresh';
 $('settings').classList.toggle('selected',layout()!=='briefing');
 $('sync').textContent=data.loading?'Refreshing sources…':data.updated?'Updated '+new Date(data.updated*1000).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}):'Waiting for headlines';
 const failures=Object.keys(data.errors).filter(id=>data.feeds.some(f=>f.id===id));
 const notice=(data.notice&&!$('feed-dialog').open?data.notice:'')||(failures.length?failures.length+' source'+(failures.length>1?'s':'')+' unavailable. Cached stories remain readable.':'');
 $('notice').hidden=!notice;$('notice').textContent=notice;
 visible=filtered();
 const lead=(!query&&layout()==='briefing'&&!['saved','unread'].includes(view))?(visible.find(s=>s.lead)||visible[0]):null;
 const featured=$('featured');featured.hidden=!lead;featured.replaceChildren();
 if(lead){const button=el('button','headline');button.append(el('h2','',lead.title));button.onclick=()=>openStory(lead);const bottom=el('div','story-bottom');bottom.append(metadata(lead),saveButton(lead));const image=photo(lead);if(image)featured.append(image);featured.append(el('div','feature-label',lead.lead?'DRUDGE · LEAD HEADLINE':'TOP OF YOUR BRIEFING'),button);if(lead.body)featured.append(el('p','excerpt',lead.body.replace(/\s+/g,' ').slice(0,210)+(lead.body.length>210?'…':'')));featured.append(bottom)}
 $('section-label').textContent=view==='saved'?'YOUR READING LIST':query?'SEARCH RESULTS':'LATEST STORIES';$('results').textContent=visible.length+' stories';
 $('stories').replaceChildren(...visible.filter(s=>s!==lead).map(storyCard));
 $('empty').hidden=visible.length>0;
 if(!visible.length){$('empty').querySelector('h2').textContent=data.loading?'Bringing in the headlines…':query?'No matching stories.':view==='saved'?'Your reading list starts here.':view==='unread'?'You’re all caught up.':'No stories yet.';$('empty').querySelector('p').textContent=query?'Try a different search.':view==='saved'?'Use ☆ beside a headline to save it for later.':'Add a source or refresh to get started.'}
 if(selected&&$('article-dialog').open)$('article-save').textContent=data.state.saved[selected.id]?'★ Saved':'☆ Save';
}
function renderManage(){$('manage-feeds').replaceChildren(...data.feeds.map(feed=>{const row=el('div','manage-row');const text=el('span','',feed.name);if(data.errors[feed.id])text.title=data.errors[feed.id];const remove=el('button','icon','×');remove.title='Remove '+feed.name;remove.setAttribute('aria-label',remove.title);remove.onclick=()=>{if(confirm('Remove '+feed.name+'? Your saved stories will stay.'))send('remove',{id:feed.id})};row.append(text,remove);return row}))}
function showFeeds(){renderManage();$('feed-notice').textContent='';$('feed-dialog').showModal();$('feed-name').focus()}
$('add').onclick=showFeeds;$('empty-add').onclick=showFeeds;$('close-feed').onclick=()=>$('feed-dialog').close();
$('feed-form').onsubmit=event=>{event.preventDefault();send('add',{name:$('feed-name').value,url:$('feed-url').value})};
$('refresh').onclick=()=>send('refresh');$('settings').onclick=()=>$('settings-dialog').showModal();
$('close-settings').onclick=()=>$('settings-dialog').close();
document.querySelectorAll('[name=layout]').forEach(input=>input.onchange=()=>send('preferences',{layout:input.value}));
$('photos').onchange=()=>send('preferences',{photos:$('photos').checked});
$('read-all').onclick=()=>send('mark_all',{ids:visible.map(s=>s.id)});
$('search').oninput=event=>{query=event.target.value.trim().toLowerCase();render()};
$('close-article').onclick=()=>$('article-dialog').close();$('article-open').onclick=()=>selected&&send('open',{id:selected.id});$('article-save').onclick=()=>selected&&send('save',{id:selected.id});
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='r'){event.preventDefault();send('refresh')}if((event.ctrlKey||event.metaKey)&&event.key==='f'){event.preventDefault();$('search').focus()}if(event.key==='/'&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]')){event.preventDefault();$('search').focus()}});
render();send('ready');
