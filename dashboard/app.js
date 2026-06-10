const SOURCE_COLORS={'Channel 13':'#6366f1','I24 NEWS':'#f43f5e','Ynet':'#22c55e','Channel 12':'#f59e0b','Kan News':'#06b6d4','Reshet 13':'#a855f7','Now 14':'#ec4899'};
const ITEMS_PER_PAGE=25;
let allData=[],filteredData=[],activeSources=new Set(),currentPage=1,chartInstances={},currentPageView='overview';

document.addEventListener('DOMContentLoaded',()=>{loadCSV();});

function loadCSV(){
    Papa.parse('../log_csv.csv',{download:true,header:true,skipEmptyLines:true,
        complete:(results)=>{
            allData=results.data.filter(r=>r.Time&&r.Source&&r['Predicted Score']).map(r=>({time:new Date(r.Time),source:r.Source.trim(),title:r.Title||'',content:r.Content||'',score:parseFloat(r['Predicted Score'])||0})).filter(r=>!isNaN(r.time.getTime())&&r.score>0).sort((a,b)=>a.time-b.time);
            const sources=[...new Set(allData.map(d=>d.source))];
            activeSources=new Set(sources);
            initFilters(sources);initSidebar(sources);applyFilters();hideLoading();
        },
        error:()=>{document.getElementById('loading-screen').innerHTML='<p style="color:#ef4444;font-size:1.1rem">שגיאה בטעינת הנתונים</p>';}
    });
}

function hideLoading(){const l=document.getElementById('loading-screen'),a=document.getElementById('app');l.classList.add('fade-out');setTimeout(()=>{l.style.display='none';a.classList.remove('hidden');},500);}

function initSidebar(sources){
    const c=document.getElementById('nav-sources');
    c.innerHTML=sources.map(s=>`<a href="#" class="nav-item" data-page="source:${s}"><span class="nav-dot" style="background:${getSourceColor(s)}"></span><span>${s}</span></a>`).join('');
    document.querySelectorAll('.nav-item').forEach(el=>{el.addEventListener('click',e=>{e.preventDefault();navigateTo(el.dataset.page);});});
    document.getElementById('back-to-overview').addEventListener('click',()=>navigateTo('overview'));
    const tog=document.getElementById('sidebar-toggle');
    tog.addEventListener('click',()=>{const sb=document.getElementById('sidebar');sb.classList.toggle('mobile-open');});
}

function navigateTo(page){
    currentPageView=page;
    document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
    const activeNav=document.querySelector(`.nav-item[data-page="${page}"]`);
    if(activeNav)activeNav.classList.add('active');
    const sb=document.getElementById('sidebar');sb.classList.remove('mobile-open');
    if(page==='overview'){
        document.getElementById('page-overview').classList.remove('hidden');
        document.getElementById('page-source').classList.add('hidden');
        document.getElementById('page-title-sub').textContent='סקירה כללית של כל המקורות';
        applyFilters();
    }else if(page.startsWith('source:')){
        const src=page.replace('source:','');
        document.getElementById('page-overview').classList.add('hidden');
        document.getElementById('page-source').classList.remove('hidden');
        document.getElementById('page-title-sub').textContent=src;
        renderSourcePage(src);
    }
}

function initFilters(sources){
    const c=document.getElementById('source-filters');c.innerHTML='';
    sources.forEach(source=>{
        const chip=document.createElement('div');chip.className='chip active';chip.dataset.source=source;
        const dot=document.createElement('span');dot.className='chip-dot';dot.style.backgroundColor=getSourceColor(source);
        chip.appendChild(dot);chip.appendChild(document.createTextNode(source));
        chip.addEventListener('click',()=>{chip.classList.toggle('active');if(chip.classList.contains('active'))activeSources.add(source);else activeSources.delete(source);currentPage=1;applyFilters();});
        c.appendChild(chip);
    });
    if(allData.length>0){
        const mn=allData[0].time.toISOString().split('T')[0],mx=allData[allData.length-1].time.toISOString().split('T')[0];
        const df=document.getElementById('date-from'),dt=document.getElementById('date-to');
        df.value=mn;dt.value=mx;df.min=mn;df.max=mx;dt.min=mn;dt.max=mx;
    }
    document.getElementById('date-from').addEventListener('change',()=>{currentPage=1;applyFilters();});
    document.getElementById('date-to').addEventListener('change',()=>{currentPage=1;applyFilters();});
    document.getElementById('reset-filters').addEventListener('click',()=>{
        activeSources=new Set([...new Set(allData.map(d=>d.source))]);
        document.querySelectorAll('.chip').forEach(c=>c.classList.add('active'));
        if(allData.length>0){document.getElementById('date-from').value=allData[0].time.toISOString().split('T')[0];document.getElementById('date-to').value=allData[allData.length-1].time.toISOString().split('T')[0];}
        document.getElementById('table-search').value='';document.getElementById('table-sort').value='time-desc';currentPage=1;applyFilters();
    });
    document.getElementById('table-search').addEventListener('input',()=>{currentPage=1;renderTable();});
    document.getElementById('table-sort').addEventListener('change',()=>{currentPage=1;renderTable();});
    document.getElementById('prev-page').addEventListener('click',()=>{currentPage--;renderTable();});
    document.getElementById('next-page').addEventListener('click',()=>{currentPage++;renderTable();});
}

function applyFilters(){
    const df=document.getElementById('date-from').value,dt=document.getElementById('date-to').value;
    filteredData=allData.filter(d=>{
        if(!activeSources.has(d.source))return false;
        if(df){const f=new Date(df);f.setHours(0,0,0,0);if(d.time<f)return false;}
        if(dt){const t=new Date(dt);t.setHours(23,59,59,999);if(d.time>t)return false;}
        return true;
    });
    updateKPIs();renderSummary();updateCharts();renderArticleLists();renderTable();
}

function updateKPIs(){
    const s=filteredData.map(d=>d.score),t=s.length,a=t?(s.reduce((a,b)=>a+b,0)/t):0,mx=t?Math.max(...s):0,mn=t?Math.min(...s):0;
    const sorted=[...s].sort((a,b)=>a-b),med=t?(t%2===0?(sorted[t/2-1]+sorted[t/2])/2:sorted[Math.floor(t/2)]):0;
    const src=new Set(filteredData.map(d=>d.source)).size;
    animateValue('kpi-total-value',t,false);animateValue('kpi-avg-value',a,true);animateValue('kpi-high-value',mx,true);
    animateValue('kpi-low-value',mn,true);animateValue('kpi-median-value',med,true);animateValue('kpi-sources-value',src,false);
    if(allData.length>0)document.getElementById('last-update-text').textContent=`עדכון: ${formatDate(allData[allData.length-1].time)}`;
    document.getElementById('total-articles-text').textContent=`${t} כתבות`;
}

function animateValue(id,target,isFloat){
    const el=document.getElementById(id),start=parseFloat(el.textContent)||0,dur=600,st=performance.now();
    function step(ct){const e=ct-st,p=Math.min(e/dur,1),ea=1-Math.pow(1-p,3),cur=start+(target-start)*ea;el.textContent=isFloat?cur.toFixed(2):Math.round(cur).toString();if(p<1)requestAnimationFrame(step);}
    requestAnimationFrame(step);
}

function renderSummary(){
    const body=document.getElementById('summary-body');
    const scores=filteredData.map(d=>d.score),total=scores.length;
    if(!total){body.innerHTML='<p style="color:var(--text-muted)">אין נתונים להצגה</p>';return;}
    const avg=(scores.reduce((a,b)=>a+b,0)/total);
    const scoreClass=avg>=6?'positive':avg>=4?'neutral':'negative';
    const scoreLabel=avg>=7?'חיובי מאוד':avg>=5.5?'חיובי':avg>=4?'ניטרלי':avg>=2.5?'שלילי':'שלילי מאוד';
    // Trend calc
    const days={};filteredData.forEach(d=>{const k=d.time.toISOString().split('T')[0];if(!days[k])days[k]=[];days[k].push(d.score);});
    const dayKeys=Object.keys(days).sort();
    let trendClass='flat',trendText='יציב',trendIcon='→';
    if(dayKeys.length>=2){
        const last7=dayKeys.slice(-7),first=dayKeys.slice(0,Math.min(7,dayKeys.length));
        const avgLast=last7.reduce((s,k)=>s+days[k].reduce((a,b)=>a+b,0)/days[k].length,0)/last7.length;
        const avgFirst=first.reduce((s,k)=>s+days[k].reduce((a,b)=>a+b,0)/days[k].length,0)/first.length;
        const diff=avgLast-avgFirst;
        if(diff>0.3){trendClass='up';trendText='מגמת עלייה';trendIcon='↑';}
        else if(diff<-0.3){trendClass='down';trendText='מגמת ירידה';trendIcon='↓';}
    }
    // Source comparison
    const srcAvg={};filteredData.forEach(d=>{if(!srcAvg[d.source])srcAvg[d.source]={t:0,c:0};srcAvg[d.source].t+=d.score;srcAvg[d.source].c++;});
    const srcList=Object.entries(srcAvg).map(([n,v])=>({name:n,avg:v.t/v.c,count:v.c})).sort((a,b)=>b.avg-a.avg);

    body.innerHTML=`
        <div class="summary-block">
            <div class="summary-block-title">📊 ציון מורל כללי</div>
            <div class="summary-block-content">
                <div class="summary-score-big ${scoreClass}">${avg.toFixed(1)}</div>
                <div style="margin:8px 0"><span class="summary-trend ${trendClass}">${trendIcon} ${trendText}</span></div>
                <div style="color:var(--text-secondary);font-size:.82rem">המורל הלאומי כרגע: <strong style="color:var(--text-primary)">${scoreLabel}</strong><br>מבוסס על ${total} כתבות מ-${srcList.length} מקורות</div>
            </div>
        </div>
        <div class="summary-block">
            <div class="summary-block-title">📰 השוואת מקורות</div>
            <div class="summary-source-list">
                ${srcList.map(s=>{const sc=s.avg>=6?'var(--accent-green)':s.avg>=4?'var(--accent-amber)':'var(--accent-red)';
                return `<div class="summary-source-row"><span class="summary-source-name"><span class="dot" style="background:${getSourceColor(s.name)}"></span>${s.name} (${s.count})</span><span class="summary-source-score" style="color:${sc}">${s.avg.toFixed(2)}</span></div>`;}).join('')}
            </div>
        </div>`;
}

function destroyChart(n){if(chartInstances[n]){chartInstances[n].destroy();chartInstances[n]=null;}}
const cD={color:'#94a3b8',borderColor:'rgba(255,255,255,0.06)',font:{family:"'Noto Sans Hebrew','Inter',sans-serif"}};
function gCO(ov={}){return{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:cD.color,font:{...cD.font,size:11},padding:16,usePointStyle:true,pointStyleWidth:12}},tooltip:{backgroundColor:'rgba(17,24,39,0.95)',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,titleColor:'#f1f5f9',bodyColor:'#94a3b8',titleFont:{...cD.font,size:13,weight:'600'},bodyFont:{...cD.font,size:12},padding:12,cornerRadius:10,displayColors:true,rtl:true,textDirection:'rtl'}},scales:{x:{ticks:{color:cD.color,font:{...cD.font,size:10}},grid:{color:cD.borderColor}},y:{ticks:{color:cD.color,font:{...cD.font,size:10}},grid:{color:cD.borderColor}}},...ov};}

function updateCharts(){renderTimelineChart();renderSourceAvgChart();renderDistributionChart();renderSourcePieChart();renderDailyCountChart();renderRangeChart();}

function renderTimelineChart(){
    destroyChart('timeline');const ctx=document.getElementById('timeline-chart').getContext('2d');
    const g={};filteredData.forEach(d=>{const dk=d.time.toISOString().split('T')[0],k=`${d.source}|${dk}`;if(!g[k])g[k]={source:d.source,date:dk,scores:[]};g[k].scores.push(d.score);});
    const sg={};Object.values(g).forEach(v=>{if(!sg[v.source])sg[v.source]=[];sg[v.source].push({x:v.date,y:v.scores.reduce((a,b)=>a+b,0)/v.scores.length});});
    const ds=Object.entries(sg).map(([s,p])=>({label:s,data:p.sort((a,b)=>a.x.localeCompare(b.x)),borderColor:getSourceColor(s),backgroundColor:getSourceColor(s)+'20',fill:true,tension:.35,borderWidth:2,pointRadius:3,pointHoverRadius:6,pointBackgroundColor:getSourceColor(s),pointBorderColor:'transparent'}));
    chartInstances['timeline']=new Chart(ctx,{type:'line',data:{datasets:ds},options:gCO({scales:{x:{type:'time',time:{unit:'day',tooltipFormat:'dd/MM/yyyy'},ticks:{color:cD.color,font:{...cD.font,size:10},maxTicksLimit:15},grid:{color:cD.borderColor}},y:{title:{display:true,text:'ציון ממוצע',color:cD.color,font:{...cD.font,size:11}},ticks:{color:cD.color,font:{...cD.font,size:10}},grid:{color:cD.borderColor}}},interaction:{mode:'index',intersect:false}})});
}

function renderSourceAvgChart(){
    destroyChart('sourceAvg');const ctx=document.getElementById('source-avg-chart').getContext('2d');
    const sa={};filteredData.forEach(d=>{if(!sa[d.source])sa[d.source]={t:0,c:0};sa[d.source].t+=d.score;sa[d.source].c++;});
    const l=Object.keys(sa),v=l.map(s=>sa[s].t/sa[s].c),c=l.map(s=>getSourceColor(s));
    chartInstances['sourceAvg']=new Chart(ctx,{type:'bar',data:{labels:l,datasets:[{label:'ציון ממוצע',data:v,backgroundColor:c.map(x=>x+'60'),borderColor:c,borderWidth:2,borderRadius:8,borderSkipped:false}]},options:gCO({indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>`ציון ממוצע: ${ctx.raw.toFixed(2)}`}}},scales:{x:{ticks:{color:cD.color},grid:{color:cD.borderColor}},y:{ticks:{color:cD.color,font:{...cD.font,size:11,weight:'500'}},grid:{display:false}}}})});
}

function renderDistributionChart(){
    destroyChart('distribution');const ctx=document.getElementById('distribution-chart').getContext('2d');
    const bins=[0,1,2,3,4,5,6,7,8,9,10],bl=bins.slice(0,-1).map((b,i)=>`${b}-${bins[i+1]}`),bc=new Array(bins.length-1).fill(0);
    filteredData.forEach(d=>{for(let i=0;i<bins.length-1;i++){if(d.score>=bins[i]&&(d.score<bins[i+1]||(i===bins.length-2&&d.score<=bins[i+1]))){bc[i]++;break;}}});
    const bC=bc.map((_,i)=>{const r=i/(bins.length-2);return r<.33?'#ef4444':r<.66?'#f59e0b':'#22c55e';});
    chartInstances['distribution']=new Chart(ctx,{type:'bar',data:{labels:bl,datasets:[{label:'כמות כתבות',data:bc,backgroundColor:bC.map(c=>c+'50'),borderColor:bC,borderWidth:2,borderRadius:6,borderSkipped:false}]},options:gCO({plugins:{legend:{display:false}},scales:{x:{title:{display:true,text:'טווח ציון',color:cD.color,font:{...cD.font,size:11}},ticks:{color:cD.color},grid:{display:false}},y:{title:{display:true,text:'כמות כתבות',color:cD.color,font:{...cD.font,size:11}},ticks:{color:cD.color},grid:{color:cD.borderColor}}}})});
}

function renderSourcePieChart(){
    destroyChart('sourcePie');const ctx=document.getElementById('source-pie-chart').getContext('2d');
    const sc={};filteredData.forEach(d=>{sc[d.source]=(sc[d.source]||0)+1;});
    const l=Object.keys(sc),v=Object.values(sc),c=l.map(s=>getSourceColor(s));
    chartInstances['sourcePie']=new Chart(ctx,{type:'doughnut',data:{labels:l,datasets:[{data:v,backgroundColor:c.map(x=>x+'80'),borderColor:c,borderWidth:2,hoverOffset:8}]},options:{responsive:true,maintainAspectRatio:false,cutout:'60%',plugins:{legend:{position:'bottom',labels:{color:cD.color,font:{...cD.font,size:11},padding:16,usePointStyle:true}},tooltip:{backgroundColor:'rgba(17,24,39,0.95)',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,titleColor:'#f1f5f9',bodyColor:'#94a3b8',rtl:true,textDirection:'rtl',callbacks:{label:ctx=>{const p=((ctx.raw/v.reduce((a,b)=>a+b,0))*100).toFixed(1);return `${ctx.label}: ${ctx.raw} כתבות (${p}%)`;}}}}}}); 
}

function renderDailyCountChart(){
    destroyChart('dailyCount');const ctx=document.getElementById('daily-count-chart').getContext('2d');
    const dc={};filteredData.forEach(d=>{const k=d.time.toISOString().split('T')[0];dc[k]=(dc[k]||0)+1;});
    const sd=Object.keys(dc).sort(),cn=sd.map(d=>dc[d]);
    chartInstances['dailyCount']=new Chart(ctx,{type:'bar',data:{labels:sd,datasets:[{label:'כתבות',data:cn,backgroundColor:'rgba(99,102,241,0.35)',borderColor:'#6366f1',borderWidth:1.5,borderRadius:4,borderSkipped:false}]},options:gCO({plugins:{legend:{display:false}},scales:{x:{type:'time',time:{unit:'day',tooltipFormat:'dd/MM/yyyy'},ticks:{color:cD.color,maxTicksLimit:15},grid:{display:false}},y:{title:{display:true,text:'כמות כתבות',color:cD.color,font:{...cD.font,size:11}},ticks:{color:cD.color,stepSize:1},grid:{color:cD.borderColor}}}})});
}

function renderRangeChart(){
    destroyChart('range');const ctx=document.getElementById('range-chart').getContext('2d');
    const ss={};filteredData.forEach(d=>{if(!ss[d.source])ss[d.source]={s:[]};ss[d.source].s.push(d.score);});
    const l=Object.keys(ss),mn=l.map(s=>Math.min(...ss[s].s)),av=l.map(s=>ss[s].s.reduce((a,b)=>a+b,0)/ss[s].s.length),mx=l.map(s=>Math.max(...ss[s].s));
    chartInstances['range']=new Chart(ctx,{type:'bar',data:{labels:l,datasets:[{label:'מינימום',data:mn,backgroundColor:'rgba(239,68,68,0.35)',borderColor:'#ef4444',borderWidth:1.5,borderRadius:4,borderSkipped:false},{label:'ממוצע',data:av,backgroundColor:'rgba(245,158,11,0.35)',borderColor:'#f59e0b',borderWidth:1.5,borderRadius:4,borderSkipped:false},{label:'מקסימום',data:mx,backgroundColor:'rgba(34,197,94,0.35)',borderColor:'#22c55e',borderWidth:1.5,borderRadius:4,borderSkipped:false}]},options:gCO({scales:{x:{ticks:{color:cD.color},grid:{display:false}},y:{ticks:{color:cD.color},grid:{color:cD.borderColor}}}})});
}

function renderArticleLists(){
    const sorted=[...filteredData].sort((a,b)=>b.score-a.score),top10=sorted.slice(0,10),bot10=sorted.slice(-10).reverse();
    document.getElementById('top-articles').innerHTML=top10.map(a=>`<div class="article-item"><span class="article-score high">${a.score.toFixed(1)}</span><div class="article-info"><div class="article-title" title="${escapeHTML(a.title)}">${escapeHTML(a.title)}</div><div class="article-meta">${a.source} • ${formatDate(a.time)}</div></div></div>`).join('');
    document.getElementById('bottom-articles').innerHTML=bot10.map(a=>`<div class="article-item"><span class="article-score low">${a.score.toFixed(1)}</span><div class="article-info"><div class="article-title" title="${escapeHTML(a.title)}">${escapeHTML(a.title)}</div><div class="article-meta">${a.source} • ${formatDate(a.time)}</div></div></div>`).join('');
}

function renderTable(){
    const search=document.getElementById('table-search').value.trim().toLowerCase(),sortBy=document.getElementById('table-sort').value;
    let data=[...filteredData];if(search)data=data.filter(d=>d.title.toLowerCase().includes(search));
    switch(sortBy){case'time-desc':data.sort((a,b)=>b.time-a.time);break;case'time-asc':data.sort((a,b)=>a.time-b.time);break;case'score-desc':data.sort((a,b)=>b.score-a.score);break;case'score-asc':data.sort((a,b)=>a.score-b.score);break;}
    const tp=Math.ceil(data.length/ITEMS_PER_PAGE)||1;if(currentPage>tp)currentPage=tp;if(currentPage<1)currentPage=1;
    const si=(currentPage-1)*ITEMS_PER_PAGE,pd=data.slice(si,si+ITEMS_PER_PAGE);
    document.getElementById('table-body').innerHTML=pd.map((d,i)=>{const sc=d.score>=7?'high':d.score<=3?'low':'mid',col=getSourceColor(d.source);return `<tr><td>${si+i+1}</td><td style="white-space:nowrap;font-size:.78rem;color:var(--text-secondary)">${formatDateTime(d.time)}</td><td><span class="source-tag" style="background:${col}20;color:${col};border:1px solid ${col}40">${d.source}</span></td><td class="table-title-cell" title="${escapeHTML(d.title)}">${escapeHTML(d.title)}</td><td><span class="score-cell ${sc}">${d.score.toFixed(2)}</span></td></tr>`;}).join('');
    document.getElementById('page-info').textContent=`עמוד ${currentPage} מתוך ${tp} (${data.length} כתבות)`;
    document.getElementById('prev-page').disabled=currentPage<=1;document.getElementById('next-page').disabled=currentPage>=tp;
}

function getSourceColor(s){return SOURCE_COLORS[s]||'#6366f1';}
function formatDate(d){return d.toLocaleDateString('he-IL',{day:'2-digit',month:'2-digit',year:'numeric'});}
function formatDateTime(d){return d.toLocaleDateString('he-IL',{day:'2-digit',month:'2-digit',year:'numeric'})+' '+d.toLocaleTimeString('he-IL',{hour:'2-digit',minute:'2-digit'});}
function escapeHTML(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
