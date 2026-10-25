'use strict';
let data={stories:[],feeds:[],folders:[],state:{read:[],saved:{},compact:false,closed:[]},errors:{},loading:true};
const articleCache=new Map();
let view='all', query='', selected=null, visible=[];
let cursor=null, storyCursor=null, navAnchor='heading', menuTarget=null, nameMode='create', addParent='', menuHandoff=false;
const $=id=>document.getElementById(id);
const send=(action,extra={})=>window.webkit?.messageHandlers.reader.postMessage(JSON.stringify({action,...extra}));
const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node};
window.applyTheme=colors=>{for(const [key,value] of Object.entries(colors)){if(/^#[0-9a-f]{6}$/i.test(value)){document.documentElement.style.setProperty('--'+({lighter_background:'panel',bright_foreground:'bright'}[key]||key),value)}}};
window.receive=payload=>{
  const place=focusPlace();
  data=payload;
  if(!Array.isArray(data.folders))data.folders=[];
  if(!data.state)data.state={};
  window.applyTheme(data.colors||{});
  render(place==='tree'&&!$('article-dialog').open);
  if(!$('article-dialog').open){
    if(place==='story')focusStories();
    else if(place==='all'||place==='unread'||place==='saved')focusLibrary(place);
  }
  if($('feed-dialog').open)$('feed-notice').textContent=data.notice||'';
  if($('name-dialog').open)$('name-notice').textContent=data.notice||'';
  if($('move-dialog').open)$('move-notice').textContent=data.notice||'';
};
function age(story){if(!story.published)return 'Headline link';const hours=Math.max(0,Math.floor((Date.now()/1000-story.published)/3600));return hours<1?'Just in':hours<24?hours+'h ago':Math.floor(hours/24)+'d ago'}
function folderFeedIds(id){
  const pending=[id], seen=new Set(), feedIds=[];
  while(pending.length){
    const current=pending.pop();
    if(seen.has(current))continue;
    seen.add(current);
    for(const folder of data.folders)if((folder.parent||'')===current)pending.push(folder.id);
    for(const feed of data.feeds)if((feed.parent||'')===current)feedIds.push(feed.id);
  }
  return feedIds;
}
function filtered(){
  let stories=view==='saved'?Object.values(data.state.saved):data.stories;
  if(view==='unread')stories=stories.filter(s=>!data.state.read.includes(s.id));
  else if(!['all','saved'].includes(view)){
    if(data.folders.some(folder=>folder.id===view)){
      const ids=new Set(folderFeedIds(view));
      stories=stories.filter(story=>ids.has(story.feed_id));
    }else stories=stories.filter(story=>story.feed_id===view);
  }
  if(query)stories=stories.filter(story=>(story.title+' '+story.source+' '+(story.body||'')).toLowerCase().includes(query));
  return stories;
}
function leadStory(){
  if(query||layout()!=='briefing'||['saved','unread'].includes(view)||!visible.length)return null;
  return visible.find(story=>story.lead)||visible[0];
}
function displayedStories(){
  const lead=leadStory();
  return lead?[lead,...visible.filter(story=>story!==lead)]:visible.slice();
}
function navButton(name,symbol,count,id){
  const button=el('button',view===id?'active':'');
  button.dataset.view=id;
  button.append(el('span','symbol',symbol),el('span','name',name),el('span','count',String(count)));
  button.onclick=()=>{view=id;navAnchor=id;render();focusLibrary(id)};
  return button;
}
function metadata(story){const meta=el('div','meta');if(!data.state.read.includes(story.id))meta.append(el('span','unread-dot'));meta.append(el('span','source',story.source),el('span','','·'),el('span','',age(story)));return meta}
function saveButton(story){const saved=!!data.state.saved[story.id];const button=el('button','save'+(saved?' saved':''),saved?'★':'☆');button.tabIndex=-1;button.title=saved?'Remove from saved':'Save story';button.setAttribute('aria-label',button.title);button.onclick=()=>send('save',{id:story.id});return button}
function requestArticle(){if(!selected)return;$('article-status').textContent='Loading reader view…';$('article-load').disabled=true;send('article',{id:selected.id})}
window.receiveArticle=result=>{if(result.body)articleCache.set(result.id,result.body);if(selected?.id!==result.id)return;$('article-load').disabled=false;$('article-load').hidden=!!result.body;if(result.body){$('article-body').textContent=result.body;$('article-status').textContent='Reader view · '+Math.max(1,Math.ceil(result.body.split(/\s+/).length/220))+' min read'}else{$('article-status').textContent=result.error||'Reader view unavailable. Feed text is shown.'}};
function openStory(story){selected=story;storyCursor=story.id;setPane('stories');applyStoryCursor();$('article-title').textContent=story.title;$('article-source').textContent=story.source+' · '+age(story);$('article-body').textContent=articleCache.get(story.id)||story.body||'This source provides a headline link. Loading the article from its publisher…';$('article-status').textContent=articleCache.has(story.id)?'Reader view':'From your feed';$('article-load').hidden=articleCache.has(story.id);$('article-load').disabled=false;$('article-save').textContent=data.state.saved[story.id]?'★ Saved':'☆ Save';if(!$('article-dialog').open)$('article-dialog').showModal();$('article-dialog').scrollTop=0;send('read',{id:story.id});if(!articleCache.has(story.id)&&(story.body||'').length<1500)requestArticle()}
$('article-load').onclick=requestArticle;
function layout(){return data.state.layout|| (data.state.compact?'headlines':'briefing')}
function unsafeImageHost(host){const name=String(host||'').replace(/^\[|\]$/g,'').split('%')[0].toLowerCase();if(!name||name==='localhost'||name.endsWith('.localhost')||name.endsWith('.local'))return true;if(/^(?:\d+|0x[0-9a-f]+)$/i.test(name))return true;const v4=/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(name);if(v4){const parts=v4.slice(1);if(parts.some(part=>part.length>1&&part.startsWith('0')))return true;const n=parts.map(Number);if(n.some(part=>part>255))return true;const a=n[0],b=n[1];return a===0||a===10||a===127||a>=224||(a===169&&b===254)||(a===172&&b>=16&&b<=31)||(a===192&&b===168)||(a===100&&b>=64&&b<=127)||(a===192&&b===0)||(a===198&&(b===18||b===19))||(a===203&&b===0&&n[2]===113)}if(name.includes(':')){if(name==='::'||name==='::1'||name.startsWith('fe80:')||name.startsWith('fc')||name.startsWith('fd'))return true;if(name.startsWith('::ffff:'))return unsafeImageHost(name.slice(7))}return false}
function photo(story){if(!data.state.photos||layout()==='headlines'||!story.image)return null;let url;try{url=new URL(story.image)}catch{return null}if(!['https:','http:'].includes(url.protocol)||url.username||url.password||unsafeImageHost(url.hostname))return null;const img=el('img','story-photo');img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';img.onerror=()=>img.remove();img.src=url.href;return img}
function storyCard(story){const card=el('article','story'+(data.state.read.includes(story.id)?' is-read':'')+(story.id===storyCursor?' cursor':''));card.dataset.story=story.id;const button=el('button','headline');button.tabIndex=story.id===storyCursor?0:-1;button.append(el('h3','',story.title));button.onclick=()=>openStory(story);const bottom=el('div','story-bottom');bottom.append(saveButton(story));const image=photo(story);if(image)card.append(image);card.append(metadata(story),button,bottom);return card}
function closedSet(){return new Set(data.state.closed||[])}
function isClosed(id){return closedSet().has(id)}
function treeFocus(){const node=document.activeElement;return !!(node&&($('sources').contains(node)||$('source-heading').contains(node)))}
function visibleRows(){return [...document.querySelectorAll('#sources .tree-row')]}
function targetFromCursor(){
  if(document.activeElement===$('add')||!cursor)return null;
  const list=cursor.kind==='folder'?data.folders:data.feeds;
  const item=list.find(entry=>entry.id===cursor.id);
  return item?{kind:cursor.kind,id:item.id,name:item.name,parent:item.parent||''}:null;
}
function setPane(pane){document.body.dataset.pane=pane}
function typing(){return ['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)}
function libraryId(){const button=document.activeElement;return button&&$('library').contains(button)?button.dataset.view||null:null}
function storyFocus(){const node=document.activeElement;return !!(node&&(node===$('stories')||$('stories').contains(node)||$('featured').contains(node)))}
function focusPlace(){if(treeFocus())return 'tree';if(storyFocus())return 'story';return libraryId()}
function storyNode(id){const safe=CSS.escape(id);return document.querySelector(`#featured[data-story="${safe}"], #stories .story[data-story="${safe}"]`)}
function applyStoryCursor(){
  for(const node of document.querySelectorAll('#featured[data-story], #stories .story')){
    const on=node.dataset.story===storyCursor;
    node.classList.toggle('cursor',on);
    const headline=node.querySelector('.headline');
    if(headline)headline.tabIndex=on?0:-1;
  }
}
function focusCursor(){
  setPane('nav');
  if(cursor){
    navAnchor='tree';
    const row=visibleRows().find(entry=>entry.dataset.id===cursor.id);
    row?.querySelector('.tree-label')?.focus();
    return;
  }
  navAnchor='heading';
  $('source-heading').focus();
}
function focusLibrary(id){
  const button=$('library').querySelector(`[data-view="${id}"]`);
  if(!button)return;
  navAnchor=id;
  setPane('nav');
  $('source-heading').classList.remove('cursor');
  button.focus();
}
function focusNav(){
  if(navAnchor==='all'||navAnchor==='unread'||navAnchor==='saved'){focusLibrary(navAnchor);return}
  focusCursor();
}
function focusStories(){
  setPane('stories');
  const stories=displayedStories();
  if(!stories.length){$('stories').focus();return}
  if(!stories.some(story=>story.id===storyCursor))storyCursor=stories[0].id;
  applyStoryCursor();
  const headline=storyNode(storyCursor)?.querySelector('.headline');
  if(headline)headline.focus();
  else $('stories').focus();
}
function moveStory(delta){
  const stories=displayedStories();
  if(!stories.length)return;
  const index=stories.findIndex(story=>story.id===storyCursor);
  const nextIndex=Math.max(0,Math.min(stories.length-1,(index<0?0:index)+delta));
  storyCursor=stories[nextIndex].id;
  applyStoryCursor();
  storyNode(storyCursor)?.querySelector('.headline')?.focus();
}
function stepArticle(delta){
  const stories=displayedStories();
  const index=stories.findIndex(story=>story.id===(selected?.id||storyCursor));
  const next=stories[index+delta];
  if(next)openStory(next);
}
function toggleClosed(id){
  const closed=closedSet();
  if(closed.has(id))closed.delete(id);else closed.add(id);
  data.state.closed=[...closed];
  render(true);
  send('closed',{ids:data.state.closed});
}
function treeRows(parent,depth){
  const rows=[];
  for(const folder of data.folders.filter(item=>(item.parent||'')===parent)){
    rows.push(treeRow(folder,'folder',depth));
    if(!isClosed(folder.id))rows.push(...treeRows(folder.id,depth+1));
  }
  for(const feed of data.feeds.filter(item=>(item.parent||'')===parent))rows.push(treeRow(feed,'feed',depth));
  return rows;
}
function treeRow(item,kind,depth){
  const row=el('div','tree-row'+(view===item.id?' active':'')+(cursor&&cursor.id===item.id?' cursor':''));
  row.dataset.id=item.id;row.dataset.kind=kind;row.dataset.parent=item.parent||'';
  row.setAttribute('role','treeitem');
  row.style.paddingLeft=(depth*12)+'px';
  if(kind==='folder'){
    const chevron=el('button','chevron',isClosed(item.id)?'▸':'▾');
    chevron.type='button';
    chevron.tabIndex=-1;
    chevron.setAttribute('aria-label',(isClosed(item.id)?'Open ':'Close ')+item.name);
    chevron.setAttribute('aria-expanded',String(!isClosed(item.id)));
    chevron.onclick=event=>{event.stopPropagation();toggleClosed(item.id)};
    row.append(chevron);
    row.setAttribute('aria-expanded',String(!isClosed(item.id)));
  }else row.append(el('span','chevron-spacer'));
  const label=el('button','tree-label');
  label.type='button';
  label.tabIndex=cursor&&cursor.id===item.id?0:-1;
  const feedIds=kind==='folder'?folderFeedIds(item.id):[item.id];
  const count=data.stories.filter(story=>feedIds.includes(story.feed_id)&&!data.state.read.includes(story.id)).length;
  if(kind==='feed'){
    const dot=el('span','source-dot');
    if(data.errors[item.id]){dot.style.background='var(--muted)';label.title='Could not refresh · Showing cached stories'}
    label.append(dot);
  }
  label.append(el('span','name',item.name),el('span','count',String(count)));
  label.onclick=()=>{cursor={kind,id:item.id};view=item.id;render(true)};
  row.addEventListener('contextmenu',event=>{event.preventDefault();cursor={kind,id:item.id};render(true);openMenu(event.clientX,event.clientY)});
  row.append(label);
  return row;
}
function render(restoreTree){
  if(!['all','unread','saved'].includes(view)&&!data.feeds.some(feed=>feed.id===view)&&!data.folders.some(folder=>folder.id===view))view='all';
  if(cursor&&!(cursor.kind==='folder'?data.folders:data.feeds).some(item=>item.id===cursor.id))cursor=null;
  document.body.classList.toggle('compact',layout()==='headlines');
  document.body.dataset.layout=layout();
  document.querySelectorAll('[name=layout]').forEach(input=>input.checked=input.value===layout());
  $('photos').checked=!!data.state.photos;
  $('date').textContent=new Date().toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'}).toUpperCase();
  const unread=data.stories.filter(story=>!data.state.read.includes(story.id)).length;
  $('library').replaceChildren(navButton('All stories','◫',data.stories.length,'all'),navButton('Unread','◉',unread,'unread'),navButton('Saved for later','☆',Object.keys(data.state.saved).length,'saved'));
  $('sources').replaceChildren(...treeRows('',0));
  $('source-heading').classList.toggle('cursor',!cursor&&document.activeElement===$('source-heading'));
  const folder=data.folders.find(item=>item.id===view);
  const feed=data.feeds.find(item=>item.id===view);
  const title=view==='all'?'Your briefing':view==='unread'?'Still to read':view==='saved'?'Saved for later':(folder||feed)?.name||'Your briefing';
  $('heading').replaceChildren(document.createTextNode(title),el('span','','.'));
  $('subtitle').textContent=view==='saved'?'The stories you want to come back to.':view==='unread'?'Catch up at your own pace.':feed?'Headlines and excerpts from '+feed.name+'.':folder?'Headlines from '+folder.name+' and the folders inside it.':data.feeds.length+' sources. One place to catch up.';
  $('refresh').disabled=data.loading;$('refresh').querySelector('span').textContent=data.loading?'Refreshing…':'Refresh';
  $('settings').classList.toggle('selected',layout()!=='briefing');
  $('sync').textContent=data.loading?'Refreshing sources…':data.updated?'Updated '+new Date(data.updated*1000).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}):'Waiting for headlines';
  const failures=Object.keys(data.errors).filter(id=>data.feeds.some(feed=>feed.id===id));
  const dialogNotice=$('feed-dialog').open||$('name-dialog').open||$('move-dialog').open;
  const notice=(data.notice&&!dialogNotice?data.notice:'')||(failures.length?failures.length+' source'+(failures.length>1?'s':'')+' unavailable. Cached stories remain readable.':'');
  $('notice').hidden=!notice;$('notice').textContent=notice;
  visible=filtered();
  const shown=displayedStories();
  if(storyCursor&&!shown.some(story=>story.id===storyCursor))storyCursor=null;
  const lead=leadStory();
  const featured=$('featured');featured.hidden=!lead;featured.replaceChildren();
  if(lead){
    featured.dataset.story=lead.id;
    featured.classList.toggle('cursor',storyCursor===lead.id);
    const button=el('button','headline');
    button.tabIndex=storyCursor===lead.id?0:-1;
    button.append(el('h2','',lead.title));
    button.onclick=()=>openStory(lead);
    const bottom=el('div','story-bottom');
    bottom.append(metadata(lead),saveButton(lead));
    const image=photo(lead);
    if(image)featured.append(image);
    featured.append(el('div','feature-label',lead.lead?'DRUDGE · LEAD HEADLINE':'TOP OF YOUR BRIEFING'),button);
    
    featured.append(bottom);
  }else{delete featured.dataset.story;featured.classList.remove('cursor')}
  $('section-label').textContent=view==='saved'?'YOUR READING LIST':query?'SEARCH RESULTS':folder?'IN THIS FOLDER':'LATEST STORIES';$('results').textContent=visible.length+' stories';
  $('stories').replaceChildren(...visible.filter(story=>story!==lead).map(storyCard));
  $('empty').hidden=visible.length>0;
  if(!visible.length){$('empty').querySelector('h2').textContent=data.loading?'Bringing in the headlines…':query?'No matching stories.':view==='saved'?'Your reading list starts here.':view==='unread'?'You’re all caught up.':'No stories yet.';$('empty').querySelector('p').textContent=query?'Try a different search.':view==='saved'?'Use ☆ beside a headline to save it for later.':'Add a source or refresh to get started.'}
  if(selected&&$('article-dialog').open)$('article-save').textContent=data.state.saved[selected.id]?'★ Saved':'☆ Save';
  if(restoreTree)focusCursor();
}
function closeMenu(){menuHandoff=true;if($('manage-menu').open)$('manage-menu').close();menuHandoff=false}
function menuButtons(){return [...$('manage-menu').querySelectorAll('button')]}
function setMenuCurrent(button){
  for(const item of menuButtons())item.classList.toggle('menu-current',item===button);
  if(button)button.focus();
}
function openMenu(x,y){
  menuTarget=targetFromCursor();
  const menu=$('manage-menu');
  menu.replaceChildren(el('div','menu-title',menuTarget?menuTarget.name:'Your sources'));
  const actions=[];
  if(!menuTarget||menuTarget.kind==='folder')actions.push(['n','New folder','create'],['a','Add feed','add']);
  if(menuTarget)actions.push(['r','Rename','rename'],['v','Move','move'],['d',menuTarget.kind==='folder'?'Delete folder':'Remove','delete']);
  for(const [key,label,action] of actions){
    const button=el('button');
    button.type='button';
    button.append(el('span','',label),el('kbd','',key));
    button.onclick=()=>runAction(action);
    button.addEventListener('mouseenter',()=>{for(const item of menuButtons())item.classList.toggle('menu-current',item===button)});
    menu.append(button);
  }
  menu.showModal();
  const width=menu.offsetWidth, height=menu.offsetHeight;
  menu.style.right='auto';
  menu.style.bottom='auto';
  menu.style.left=Math.max(8,Math.min(x,window.innerWidth-width-8))+'px';
  menu.style.top=Math.max(8,Math.min(y,window.innerHeight-height-8))+'px';
  const first=menu.querySelector('button');
  if(first)setMenuCurrent(first);
  requestAnimationFrame(()=>{
    if(menu.open&&!menu.contains(document.activeElement))setMenuCurrent(menu.querySelector('button.menu-current')||menu.querySelector('button'));
  });
}
function openMenuAtCursor(){
  const row=cursor&&visibleRows().find(entry=>entry.dataset.id===cursor.id);
  const rect=(row||$('source-heading')).getBoundingClientRect();
  openMenu(rect.right+8,rect.top);
}
function openAdd(parent){
  addParent=parent||'';
  const folder=data.folders.find(item=>item.id===addParent);
  $('feed-place').textContent=folder?'Inside '+folder.name+'.':'Added at the top level.';
  $('feed-notice').textContent='';
  $('feed-name').value='';$('feed-url').value='';
  $('feed-dialog').showModal();
  $('feed-name').focus();
}
function openName(mode,target){
  nameMode=mode;menuTarget=target;
  $('name-title').textContent=mode==='create'?'New folder':'Rename';
  $('name-input').value=mode==='rename'&&target?target.name:'';
  $('name-notice').textContent='';
  $('name-dialog').showModal();
  $('name-input').focus();
  $('name-input').select();
}
function moveChoices(target){
  const blocked=new Set();
  if(target.kind==='folder'){
    const stack=[target.id];
    while(stack.length){
      const id=stack.pop();
      if(blocked.has(id))continue;
      blocked.add(id);
      for(const folder of data.folders)if((folder.parent||'')===id)stack.push(folder.id);
    }
  }
  const choices=[{id:'',name:'Top level'}];
  const walk=(parent,depth)=>{
    for(const folder of data.folders.filter(item=>(item.parent||'')===parent)){
      if(!blocked.has(folder.id))choices.push({id:folder.id,name:`${'· '.repeat(depth)}${folder.name}`});
      walk(folder.id,depth+1);
    }
  };
  walk('',0);
  return choices;
}
function openMove(target){
  menuTarget=target;
  $('move-title').textContent='Move '+target.name;
  $('move-notice').textContent='';
  $('move-parent').replaceChildren(...moveChoices(target).map(choice=>{
    const option=el('option','',choice.name);
    option.value=choice.id;
    if((target.parent||'')===choice.id)option.selected=true;
    return option;
  }));
  $('move-dialog').showModal();
  $('move-parent').focus();
}
function runAction(action){
  const target=menuTarget;
  closeMenu();
  if(action==='create')openName('create',target);
  else if(action==='add')openAdd(target&&target.kind==='folder'?target.id:'');
  else if(action==='rename'&&target)openName('rename',target);
  else if(action==='move'&&target)openMove(target);
  else if(action==='delete'&&target){
    const message=target.kind==='folder'
      ?'Delete '+target.name+'? Feeds and folders inside it move up one level. Saved stories stay.'
      :'Remove '+target.name+'? Your saved stories will stay.';
    if(confirm(message))send('remove',{id:target.id});
  }
}
function dialogOpen(){return [...document.querySelectorAll('dialog')].some(dialog=>dialog.open)}
function onTreeKey(event){
  if(event.altKey||event.ctrlKey||event.metaKey||dialogOpen())return;
  if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))return;
  if(!treeFocus())return;
  const rows=visibleRows();
  const index=rows.findIndex(row=>cursor&&row.dataset.id===cursor.id);
  if(event.key==='ArrowDown'){
    event.preventDefault();
    const next=rows[index+1];
    if(next){cursor={kind:next.dataset.kind,id:next.dataset.id};render(true)}
    return;
  }
  if(event.key==='ArrowUp'){
    event.preventDefault();
    if(index>0){
      const previous=rows[index-1];
      cursor={kind:previous.dataset.kind,id:previous.dataset.id};
      render(true);
      return;
    }
    if(cursor){cursor=null;render(true);return}
    const buttons=[...$('library').querySelectorAll('button')];
    if(buttons.length)focusLibrary(buttons[buttons.length-1].dataset.view);
    return;
  }
  if(event.key==='ArrowRight'&&cursor?.kind==='folder'){
    event.preventDefault();
    if(isClosed(cursor.id))toggleClosed(cursor.id);
    else{const child=rows.find(row=>row.dataset.parent===cursor.id);if(child){cursor={kind:child.dataset.kind,id:child.dataset.id};render(true)}}
    return;
  }
  if(event.key==='ArrowLeft'&&cursor){
    event.preventDefault();
    if(cursor.kind==='folder'&&!isClosed(cursor.id))toggleClosed(cursor.id);
    else{
      const parent=rows.find(row=>row.dataset.id===(cursor.kind==='folder'?data.folders:data.feeds).find(item=>item.id===cursor.id)?.parent);
      if(parent)cursor={kind:parent.dataset.kind,id:parent.dataset.id};
      else cursor=null;
      render(true);
    }
    return;
  }
  if(event.key==='Enter'&&cursor){event.preventDefault();view=cursor.id;render(true);return}
  if(event.key==='m'||event.key==='ContextMenu'||(event.key==='F10'&&event.shiftKey)){event.preventDefault();openMenuAtCursor()}
}
function blockingDialog(){return ['manage-menu','name-dialog','move-dialog','feed-dialog','settings-dialog'].some(id=>$(id).open)}
function onLibraryKey(event){
  const buttons=[...$('library').querySelectorAll('button')];
  const index=buttons.indexOf(document.activeElement);
  if(index<0)return false;
  if(event.key==='ArrowDown'){
    event.preventDefault();
    if(index<buttons.length-1)focusLibrary(buttons[index+1].dataset.view);
    else{cursor=null;render(true)}
    return true;
  }
  if(event.key==='ArrowUp'){
    event.preventDefault();
    if(index>0)focusLibrary(buttons[index-1].dataset.view);
    return true;
  }
  if(event.key==='Enter'){event.preventDefault();navAnchor=buttons[index].dataset.view;buttons[index].click();return true}
  return false;
}
function onStoryKey(event){
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();moveStory(event.key==='ArrowDown'?1:-1);return}
  if(event.key==='s'||event.key==='S'){
    event.preventDefault();
    const story=displayedStories().find(item=>item.id===storyCursor);
    if(story)send('save',{id:story.id});
    return;
  }
  if(event.key==='Enter'){
    event.preventDefault();
    const story=displayedStories().find(item=>item.id===storyCursor);
    if(story)openStory(story);
  }
}
function onReadingKey(event){
  if(event.altKey||event.ctrlKey||event.metaKey||dialogOpen())return;
  if(typing())return;
  if(onLibraryKey(event))return;
  if(storyFocus()){onStoryKey(event);return}
  onTreeKey(event);
}
$('add').onclick=()=>openAdd('');
$('empty-add').onclick=()=>openAdd('');
$('close-feed').onclick=()=>$('feed-dialog').close();
$('feed-form').onsubmit=event=>{event.preventDefault();send('add',{name:$('feed-name').value,url:$('feed-url').value,parent:addParent||''});$('feed-dialog').close()};
$('name-form').onsubmit=event=>{
  event.preventDefault();
  const name=$('name-input').value, target=menuTarget, mode=nameMode;
  $('name-dialog').close();
  if(mode==='create')send('add_folder',{name,parent:target?.kind==='folder'?target.id:''});
  else if(target)send('rename',{id:target.id,name});
};
$('close-name').onclick=()=>$('name-dialog').close();
$('move-form').onsubmit=event=>{event.preventDefault();const target=menuTarget;const parent=$('move-parent').value;$('move-dialog').close();if(target)send('move',{id:target.id,parent})};
$('close-move').onclick=()=>$('move-dialog').close();
$('manage-menu').addEventListener('close',()=>{if(!menuHandoff)focusCursor()});
for(const id of ['name-dialog','move-dialog','feed-dialog'])$(id).addEventListener('close',()=>{if(!dialogOpen())focusCursor()});
$('manage-menu').addEventListener('click',event=>{
  const rect=$('manage-menu').getBoundingClientRect();
  const inside=event.clientX>=rect.left&&event.clientX<=rect.right&&event.clientY>=rect.top&&event.clientY<=rect.bottom;
  if(!inside)$('manage-menu').close();
});
$('source-heading').addEventListener('contextmenu',event=>{
  if(event.target.closest('#add'))return;
  event.preventDefault();
  cursor=null;
  render(false);
  openMenu(event.clientX,event.clientY);
});
$('source-heading').addEventListener('focus',()=>{
  if(document.activeElement!==$('source-heading'))return;
  if(cursor){cursor=null;render(false)}
  else $('source-heading').classList.add('cursor');
});
$('refresh').onclick=()=>send('refresh');$('settings').onclick=()=>$('settings-dialog').showModal();
$('close-settings').onclick=()=>$('settings-dialog').close();
document.querySelectorAll('[name=layout]').forEach(input=>input.onchange=()=>send('preferences',{layout:input.value}));
$('photos').onchange=()=>send('preferences',{photos:$('photos').checked});
$('read-all').onclick=()=>send('mark_all',{ids:visible.map(story=>story.id)});
$('search').oninput=event=>{query=event.target.value.trim().toLowerCase();render()};
$('close-article').onclick=()=>$('article-dialog').close();$('article-open').onclick=()=>selected&&send('open',{id:selected.id});$('article-save').onclick=()=>selected&&send('save',{id:selected.id});
$('article-dialog').addEventListener('close',()=>{if(!dialogOpen())focusStories()});
document.addEventListener('keydown',event=>{
  if((event.ctrlKey||event.metaKey)&&event.key==='r'){event.preventDefault();send('refresh')}
  if((event.ctrlKey||event.metaKey)&&event.key==='f'){event.preventDefault();$('search').focus()}
  if($('manage-menu').open&&!event.ctrlKey&&!event.metaKey&&!event.altKey){
    const buttons=menuButtons();
    const current=buttons.findIndex(button=>button.classList.contains('menu-current'));
    if(event.key==='ArrowDown'||event.key==='ArrowUp'){
      event.preventDefault();
      if(!buttons.length)return;
      const next=current<0
        ?(event.key==='ArrowDown'?buttons[0]:buttons[buttons.length-1])
        :buttons[(current+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length];
      setMenuCurrent(next);
      return;
    }
    if(event.key==='Enter'){
      event.preventDefault();
      (buttons[current]||buttons[0])?.click();
      return;
    }
    const action={n:'create',a:'add',r:'rename',v:'move',d:'delete','Delete':'delete','Backspace':'delete'}[event.key];
    if(action){event.preventDefault();runAction(action);return}
  }
  if($('article-dialog').open&&!typing()&&!event.ctrlKey&&!event.metaKey){
    if(!event.altKey&&(event.key==='n'||event.key==='p')){event.preventDefault();stepArticle(event.key==='n'?1:-1);return}
    if(!event.altKey&&(event.key==='s'||event.key==='S')){event.preventDefault();$('article-save').click();return}
    if(!event.altKey&&(event.key==='o'||event.key==='O')){event.preventDefault();$('article-open').click();return}
    if(event.altKey&&(event.key==='ArrowDown'||event.key==='ArrowUp')){event.preventDefault();stepArticle(event.key==='ArrowDown'?1:-1);return}
  }
  if(event.ctrlKey&&!event.metaKey&&!event.altKey&&!event.shiftKey&&!typing()&&!blockingDialog()){
    if(event.key==='ArrowLeft'){event.preventDefault();if($('article-dialog').open)$('article-dialog').close();focusNav();return}
    if(event.key==='ArrowRight'){event.preventDefault();if($('article-dialog').open)$('article-dialog').close();focusStories();return}
  }
  if(event.key==='Escape'&&document.activeElement===$('search')){event.preventDefault();focusNav();return}
  if(event.key==='/'&&!typing()&&!dialogOpen()){event.preventDefault();$('search').focus();return}
  onReadingKey(event);
});
render();send('ready');
