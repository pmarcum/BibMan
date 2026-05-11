(function(){
  var u='__GAS_URL__';
  var c='__CREDENTIAL__';
  var url=window.location.href;
  var identifier=null;
  var m=url.match(/arxiv\.org\/(?:pdf|abs)\/([\w.]+)/);
  if(m)identifier=m[1];
  if(!identifier){m=url.match(/link_gateway\/([^\/]+)\//);if(m)identifier=decodeURIComponent(m[1]);}
  if(!identifier){m=url.match(/\/abs\/([^\/\?#]+)/);if(m)identifier=decodeURIComponent(m[1]);}
  if(!identifier){
    var doi=document.querySelector('meta[name="citation_doi"]');
    var ax=document.querySelector('meta[name="citation_arxiv_id"]');
    var bib=document.querySelector('meta[name="citation_bibcode"]');
    if(doi)identifier=doi.content;
    else if(ax)identifier=ax.content;
    else if(bib)identifier=bib.content;
  }
  var ov=document.createElement('div');
  ov.id='__bm_ov__';
  ov.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.65);z-index:2147483647;font-family:monospace';
  var box=document.createElement('div');
  box.style.cssText='background:#17171a;border:1px solid #353540;border-radius:8px;padding:20px;width:430px;max-width:98vw;color:#e8e8f0;font-size:13px;max-height:90vh;overflow-y:auto;cursor:move;user-select:none;position:absolute';
  box.innerHTML='<div style="color:#7eb8f7;font-size:10px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:14px">\uD83D\uDCDA Add to BibMan</div>'
    +'<div id="__bm_body__"><div style="color:#888;text-align:center;padding:18px 0">\u23F3 Extracting metadata...</div></div>';
  ov.appendChild(box);
  document.body.appendChild(ov);
  var vw=window.innerWidth,vh=window.innerHeight;
  var bw=Math.min(430,vw*0.94);
  box.style.left=Math.max(0,Math.round((vw-bw)/2))+'px';
  box.style.top=Math.max(0,Math.round((vh-320)/2))+'px';
  var isDragging=false,dragStartX=0,dragStartY=0,boxStartX=0,boxStartY=0;
  box.addEventListener('mousedown',function(e){
    if(e.target.tagName==='INPUT'||e.target.tagName==='BUTTON'||e.target.tagName==='SELECT')return;
    isDragging=true;dragStartX=e.clientX;dragStartY=e.clientY;
    boxStartX=parseInt(box.style.left)||0;boxStartY=parseInt(box.style.top)||0;
    e.preventDefault();
  }); 
  document.addEventListener('mousemove',function(e){
    if(isDragging){
      box.style.left=(boxStartX+(e.clientX-dragStartX))+'px';
      box.style.top=(boxStartY+(e.clientY-dragStartY))+'px';
    }
    if(isResizing){
      var newW=Math.max(280,Math.min(700,resStartW+(e.clientX-resStartX)));
      box.style.width=newW+'px';
    }
  });
  document.addEventListener('mouseup',function(){isDragging=false;isResizing=false;});
  var rsz=document.createElement('div');
  rsz.style.cssText='position:absolute;bottom:0;right:0;width:14px;height:14px;cursor:se-resize;opacity:0.4;background:linear-gradient(135deg,transparent 50%,#888 50%)';
  box.appendChild(rsz);
  var isResizing=false,resStartX=0,resStartW=0;
  rsz.addEventListener('mousedown',function(e){
    isResizing=true;resStartX=e.clientX;resStartW=box.offsetWidth;
    e.preventDefault();e.stopPropagation();
  });  
  ov.addEventListener('click',function(e){if(e.target===ov)ov.remove();});
  fetch(u,{
    method:'POST',
    headers:{'Content-Type':'text/plain'},
    body:JSON.stringify({credential:c,action:'extract_and_preview',url:url,identifier:identifier,title:document.title})
  })
  .then(function(r){return r.json();})
  .then(function(meta){
    var body=document.getElementById('__bm_body__');
    if(!body)return;
    if(meta.error){
      body.innerHTML='<div style="color:#f77e7e;margin-bottom:12px">\u26A0 '+meta.error+'</div>'
        +'<div style="text-align:right"><button id="__bm_cls__" style="padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer">Close</button></div>';
      document.getElementById('__bm_cls__').onclick=function(){ov.remove();};
      return;
    }
    function fld(label,id,val){
      return '<div style="display:flex;align-items:center;margin-bottom:4px;gap:6px">'
        +'<div style="font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.1em;width:58px;flex-shrink:0;text-align:right">'+label+'</div>'
        +'<input id="'+id+'" style="flex:1;background:#0f0f11;border:1px solid #353540;border-radius:3px;padding:3px 6px;color:#e8e8f0;font-size:11px;box-sizing:border-box" value="'+(String(val||'').replace(/"/g,'&quot;'))+'">'
        +'</div>';
    }
    var src=meta.source||'unknown';
    var srcColor=src==='ads'?'#7ef7c2':src.startsWith('ads')?'#f7c97e':'#888';
    body.innerHTML=
      fld('Title','__bm_t__',meta.title||'')
      +fld('Authors','__bm_a__',meta.authors||'')
      +fld('Year','__bm_y__',meta.year||'')
      +fld('Journal','__bm_j__',meta.journal||'')
      +fld('Volume','__bm_v__',meta.volume||'')
      +fld('Pages','__bm_p__',meta.pages||'')
      +fld('DOI','__bm_d__',meta.doi||'')
      +fld('arXiv ID','__bm_x__',meta.arxiv_id||'')
      +'<div style="display:flex;align-items:center;margin-bottom:4px;gap:6px">'
      +'<div style="font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.1em;width:58px;flex-shrink:0;text-align:right">Library</div>'
      +'<select id="__bm_lib__" style="flex:1;background:#0f0f11;border:1px solid #353540;border-radius:3px;padding:3px 6px;color:#e8e8f0;font-size:11px;box-sizing:border-box">'
      +'<option value="">Loading...</option>'
      +'</select>'
      +'</div>'
      +'<div style="font-size:10px;color:#555;margin-bottom:8px">Other functions: <a href="'+u+'" target="_blank" style="color:#7eb8f7">BibMan Dashboard</a></div>'
      +'<div style="font-size:10px;margin-bottom:14px">Source: <span style="color:'+srcColor+'">'+src+'</span></div>'
      +'<div style="display:flex;gap:8px;justify-content:flex-end">'
      +'<button id="__bm_can__" style="padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer">Cancel</button>'
      +'<button id="__bm_sav__" style="padding:5px 14px;background:#7eb8f7;border:none;color:#000;border-radius:4px;cursor:pointer;font-weight:600">Add to BibMan</button>'
      +'</div>';
    document.getElementById('__bm_can__').onclick=function(){ov.remove();};
    fetch(u,{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify({credential:c,action:'get_libraries'})})
    .then(function(r){return r.json();})
    .then(function(ld){
      var sel=document.getElementById('__bm_lib__');
      if(!sel||!ld.libraries)return;
      sel.innerHTML=ld.libraries.map(function(l){
        return '<option value="'+l.name+'"'+(l.name===ld.current?' selected':'')+'>'+l.name+'</option>';
      }).join('')+'<option value="__db__">+ New (use Dashboard)</option>';
    })
    .catch(function(){
      var sel=document.getElementById('__bm_lib__');
      if(sel)sel.innerHTML='<option value="">Default library</option>';
    });
    document.getElementById('__bm_sav__').onclick=function(){
      var btn=document.getElementById('__bm_sav__');
      btn.textContent='Saving...';btn.disabled=true;
      var lv=document.getElementById('__bm_lib__').value;
      fetch(u,{
        method:'POST',
        headers:{'Content-Type':'text/plain'},
        body:JSON.stringify({
          credential:c,action:'save_captured',url:url,
          title:document.getElementById('__bm_t__').value,
          authors:document.getElementById('__bm_a__').value,
          year:document.getElementById('__bm_y__').value,
          journal:document.getElementById('__bm_j__').value,
          volume:document.getElementById('__bm_v__').value,
          pages:document.getElementById('__bm_p__').value,
          doi:document.getElementById('__bm_d__').value,
          arxiv_id:document.getElementById('__bm_x__').value,
          library:lv==='__db__'?'':lv
        })
      })
      .then(function(r){return r.json();})
      .then(function(result){
        var body2=document.getElementById('__bm_body__');
        if(result.error){
          body2.innerHTML='<div style="color:#f77e7e">'+result.error+'</div>'
            +'<button id="__bm_cls2__" style="margin-top:10px;padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer">Close</button>';
          document.getElementById('__bm_cls2__').onclick=function(){ov.remove();};
        }else{
          body2.innerHTML='<div style="color:#7ef7c2;text-align:center;padding:16px">Added: '+(result.bibkey||result.message||'done')+'</div>';
          setTimeout(function(){ov.remove();},2000);
        }
      })
      .catch(function(e){alert('BibMan save error: '+e.message);ov.remove();});
    };
  })
  .catch(function(e){
    var body=document.getElementById('__bm_body__');
    var msg=e.message||'unknown error';
    var isPdf=url.indexOf('.pdf')>-1;
    var isCors=msg.indexOf('fetch')>-1||msg.indexOf('CORS')>-1;
    var html=(isCors&&isPdf)
      ?'<div style="color:#f7c97e">\u26A0 Raw PDF page - please go to the abstract page and try again.</div><div style="text-align:right"><button id="__bm_e__" style="padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer">Close</button></div>'
      :'<div style="color:#f77e7e">Error: '+msg+'</div><button onclick="document.getElementById(\'__bm_ov__\').remove()" style="margin-top:10px;padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer">Close</button>';
    if(body)body.innerHTML=html;
    if(isCors&&isPdf)document.getElementById('__bm_e__').onclick=function(){ov.remove();};
  });
})();
