/* Source Page Logic */
let srcPage = 1;
let srcCharts = {};

function destroySrcChart(n){if(srcCharts[n]){srcCharts[n].destroy();srcCharts[n]=null;}}

function renderSourcePage(sourceName){
    const data = allData.filter(d=>d.source===sourceName);
    const scores = data.map(d=>d.score);
    const total=scores.length, avg=total?(scores.reduce((a,b)=>a+b,0)/total):0;
    const max=total?Math.max(...scores):0, min=total?Math.min(...scores):0;
    const sorted=[...scores].sort((a,b)=>a-b);
    const median=total?(total%2===0?(sorted[total/2-1]+sorted[total/2])/2:sorted[Math.floor(total/2)]):0;

    document.getElementById('source-page-title').textContent=sourceName;
    document.getElementById('source-page-subtitle').textContent=`${total} כתבות נותחו`;
    document.getElementById('source-hero-dot').style.backgroundColor=getSourceColor(sourceName);
    document.getElementById('src-kpi-total-val').textContent=total;
    document.getElementById('src-kpi-avg-val').textContent=avg.toFixed(2);
    document.getElementById('src-kpi-high-val').textContent=max.toFixed(2);
    document.getElementById('src-kpi-low-val').textContent=min.toFixed(2);
    document.getElementById('src-kpi-median-val').textContent=median.toFixed(2);

    // Timeline
    destroySrcChart('timeline');
    const grouped={};
    data.forEach(d=>{const dk=d.time.toISOString().split('T')[0];if(!grouped[dk])grouped[dk]={s:[],c:0};grouped[dk].s.push(d.score);grouped[dk].c++;});
    const dates=Object.keys(grouped).sort();
    const color=getSourceColor(sourceName);
    srcCharts['timeline']=new Chart(document.getElementById('src-timeline-chart').getContext('2d'),{
        type:'line',data:{labels:dates,datasets:[{label:sourceName,data:dates.map(d=>grouped[d].s.reduce((a,b)=>a+b,0)/grouped[d].s.length),
        borderColor:color,backgroundColor:color+'20',fill:true,tension:.35,borderWidth:2,pointRadius:3,pointBackgroundColor:color}]},
        options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{rtl:true,textDirection:'rtl',backgroundColor:'rgba(17,24,39,0.95)',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,titleColor:'#f1f5f9',bodyColor:'#94a3b8'}},
        scales:{x:{type:'time',time:{unit:'day',tooltipFormat:'dd/MM/yyyy'},ticks:{color:'#94a3b8',maxTicksLimit:15},grid:{color:'rgba(255,255,255,0.06)'}},
        y:{ticks:{color:'#94a3b8'},grid:{color:'rgba(255,255,255,0.06)'}}}}
    });

    // Distribution
    destroySrcChart('dist');
    const bins=[0,1,2,3,4,5,6,7,8,9,10],binL=bins.slice(0,-1).map((b,i)=>`${b}-${bins[i+1]}`),binC=new Array(bins.length-1).fill(0);
    data.forEach(d=>{for(let i=0;i<bins.length-1;i++){if(d.score>=bins[i]&&(d.score<bins[i+1]||(i===bins.length-2&&d.score<=bins[i+1]))){binC[i]++;break;}}});
    const bColors=binC.map((_,i)=>{const r=i/(bins.length-2);return r<.33?'#ef4444':r<.66?'#f59e0b':'#22c55e';});
    srcCharts['dist']=new Chart(document.getElementById('src-distribution-chart').getContext('2d'),{
        type:'bar',data:{labels:binL,datasets:[{data:binC,backgroundColor:bColors.map(c=>c+'50'),borderColor:bColors,borderWidth:2,borderRadius:6,borderSkipped:false}]},
        options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#94a3b8'},grid:{display:false}},y:{ticks:{color:'#94a3b8'},grid:{color:'rgba(255,255,255,0.06)'}}}}
    });

    // Daily count
    destroySrcChart('daily');
    srcCharts['daily']=new Chart(document.getElementById('src-daily-chart').getContext('2d'),{
        type:'bar',data:{labels:dates,datasets:[{data:dates.map(d=>grouped[d].c),backgroundColor:color+'40',borderColor:color,borderWidth:1.5,borderRadius:4,borderSkipped:false}]},
        options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{type:'time',time:{unit:'day',tooltipFormat:'dd/MM/yyyy'},ticks:{color:'#94a3b8',maxTicksLimit:15},grid:{display:false}},y:{ticks:{color:'#94a3b8',stepSize:1},grid:{color:'rgba(255,255,255,0.06)'}}}}
    });

    // Table
    srcPage=1;
    const searchEl=document.getElementById('src-table-search'),sortEl=document.getElementById('src-table-sort');
    searchEl.value='';sortEl.value='time-desc';
    searchEl.oninput=()=>{srcPage=1;renderSrcTable(sourceName);};
    sortEl.onchange=()=>{srcPage=1;renderSrcTable(sourceName);};
    document.getElementById('src-prev-page').onclick=()=>{srcPage--;renderSrcTable(sourceName);};
    document.getElementById('src-next-page').onclick=()=>{srcPage++;renderSrcTable(sourceName);};
    renderSrcTable(sourceName);
}

function renderSrcTable(sourceName){
    const search=document.getElementById('src-table-search').value.trim().toLowerCase();
    const sortBy=document.getElementById('src-table-sort').value;
    let data=allData.filter(d=>d.source===sourceName);
    if(search)data=data.filter(d=>d.title.toLowerCase().includes(search));
    switch(sortBy){case'time-desc':data.sort((a,b)=>b.time-a.time);break;case'time-asc':data.sort((a,b)=>a.time-b.time);break;case'score-desc':data.sort((a,b)=>b.score-a.score);break;case'score-asc':data.sort((a,b)=>a.score-b.score);break;}
    const pp=25,tp=Math.ceil(data.length/pp)||1;
    if(srcPage>tp)srcPage=tp;if(srcPage<1)srcPage=1;
    const si=(srcPage-1)*pp,pd=data.slice(si,si+pp);
    document.getElementById('src-table-body').innerHTML=pd.map((d,i)=>{
        const sc=d.score>=7?'high':d.score<=3?'low':'mid';
        return `<tr><td>${si+i+1}</td><td style="white-space:nowrap;font-size:.78rem;color:var(--text-secondary)">${formatDateTime(d.time)}</td><td class="table-title-cell" title="${escapeHTML(d.title)}">${escapeHTML(d.title)}</td><td><span class="score-cell ${sc}">${d.score.toFixed(2)}</span></td></tr>`;
    }).join('');
    document.getElementById('src-page-info').textContent=`עמוד ${srcPage} מתוך ${tp} (${data.length} כתבות)`;
    document.getElementById('src-prev-page').disabled=srcPage<=1;
    document.getElementById('src-next-page').disabled=srcPage>=tp;
}
