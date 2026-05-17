(function(){
  var u='__GAS_URL__';
  var c='__CREDENTIAL__';
  var dashboard='__DASHBOARD_URL__';
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
  box.style.cssText='background:#17171a;border:1px solid #353540;border-radius:8px;padding:20px;width:430px;max-width:98vw;color:#e8e8f0;font-size:13px;max-height:90vh;overflow-y:auto;cursor:move;user-select:none;position:absolute;box-sizing:border-box';
  var hdr=document.createElement('div');
  hdr.style.cssText='color:#7eb8f7;font-size:10px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:14px';
  hdr.textContent='Add to BibMan';
  box.appendChild(hdr);
  var bdy=document.createElement('div');
  bdy.id='__bm_body__';
  var loading=document.createElement('div');
  loading.style.cssText='color:#888;text-align:center;padding:18px 0';
  loading.textContent='Extracting metadata...';
  bdy.appendChild(loading);
  box.appendChild(bdy);
  var rsz=document.createElement('div');
  rsz.style.cssText='position:absolute;bottom:0;right:0;width:14px;height:14px;cursor:se-resize;opacity:0.5;background:linear-gradient(135deg,transparent 50%,#888 50%);flex-shrink:0';
  box.appendChild(rsz);
  ov.appendChild(box);
  document.body.appendChild(ov);
  var vw=window.innerWidth,vh=window.innerHeight;
  var bw=Math.min(430,vw*0.94);
  box.style.left=Math.max(0,Math.round((vw-bw)/2))+'px';
  box.style.top=Math.max(0,Math.round((vh-320)/2))+'px';
  var isDragging=false,isResizing=false;
  var dragStartX=0,dragStartY=0,boxStartX=0,boxStartY=0;
  var resStartX=0,resStartW=0;
  box.addEventListener('mousedown',function(e){
    if(e.target===rsz)return;
    if(e.target.tagName==='INPUT'||e.target.tagName==='BUTTON'||e.target.tagName==='SELECT')return;
    isDragging=true;dragStartX=e.clientX;dragStartY=e.clientY;
    boxStartX=parseInt(box.style.left)||0;boxStartY=parseInt(box.style.top)||0;
    e.preventDefault();
  });
  rsz.addEventListener('mousedown',function(e){
    isResizing=true;resStartX=e.clientX;resStartW=box.offsetWidth;
    e.preventDefault();e.stopPropagation();
  });
  document.addEventListener('mousemove',function(e){
    if(isDragging){
      box.style.left=(boxStartX+(e.clientX-dragStartX))+'px';
      box.style.top=(boxStartY+(e.clientY-dragStartY))+'px';
    }
    if(isResizing){
      var newW=Math.max(280,Math.min(900,resStartW+(e.clientX-resStartX)));
      box.style.width=newW+'px';
    }
  });
  document.addEventListener('mouseup',function(){isDragging=false;isResizing=false;});
  ov.addEventListener('click',function(e){if(e.target===ov)ov.remove();});

  // ── Update notice helper ───────────────────────────────────────────────────
  // Called with any response object. If ping_update_available is set and the
  // notice hasn't been shown yet this session, inserts a dismissible strip
  // at the top of the box just below the header.
  var _updateNoticeShown=false;
  function _maybeShowUpdateNotice(resp){
    if(_updateNoticeShown)return;
    if(!resp||!resp.bibman_bookmarklet_capture_update_available)return;
    _updateNoticeShown=true;
    var strip=document.createElement('div');
    strip.style.cssText='background:rgba(247,201,126,0.12);border:1px solid rgba(247,201,126,0.4);'
      +'border-radius:4px;padding:6px 10px;margin-bottom:12px;font-size:10px;'
      +'color:#f7c97e;display:flex;align-items:flex-start;gap:8px;line-height:1.5';
    var txt=document.createElement('div');
    txt.style.cssText='flex:1';
    var notes=resp.bibman_bookmarklet_capture_webapp_notes?(' — '+resp.bibman_bookmarklet_capture_webapp_notes):'';
    txt.innerHTML='<strong>BibMan bookmarklet update available</strong>'+notes
      +'<br><span style="opacity:0.7">Ask your admin to redeploy the bookmarklet getter webapp, '
      +'then reinstall your bookmarklet from the BibMan dashboard.</span>';
    var dismiss=document.createElement('button');
    dismiss.textContent='✕';
    dismiss.style.cssText='background:transparent;border:none;color:#f7c97e;cursor:pointer;'
      +'font-size:12px;padding:0;flex-shrink:0;opacity:0.7;line-height:1';
    dismiss.onclick=function(){strip.remove();};
    strip.appendChild(txt);
    strip.appendChild(dismiss);
    // Insert after header (hdr), before body (bdy)
    box.insertBefore(strip,bdy);
  }

  fetch(u,{
    method:'POST',
    headers:{'Content-Type':'text/plain'},
    body:JSON.stringify({credential:c,action:'extract_and_preview',url:url,identifier:identifier,title:document.title})
  })
  .then(function(r){return r.json();})
  .then(function(meta){
    _maybeShowUpdateNotice(meta);
    var body=document.getElementById('__bm_body__');
    if(!body)return;
    if(meta.error){
      var ed=document.createElement('div');
      ed.style.cssText='color:#f77e7e;margin-bottom:12px';
      ed.textContent=meta.error;
      var ecb=document.createElement('button');
      ecb.textContent='Close';
      ecb.style.cssText='padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer';
      ecb.onclick=function(){ov.remove();};
      var ewr=document.createElement('div');
      ewr.style.cssText='text-align:right';
      ewr.appendChild(ecb);
      body.innerHTML='';
      body.appendChild(ed);
      body.appendChild(ewr);
      return;
    }
    function fld(label,id,val){
      var row=document.createElement('div');
      row.style.cssText='display:flex;align-items:center;margin-bottom:4px;gap:6px';
      var lbl=document.createElement('div');
      lbl.style.cssText='font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.1em;width:58px;flex-shrink:0;text-align:right';
      lbl.textContent=label;
      var inp=document.createElement('input');
      inp.id=id;
      inp.style.cssText='flex:1;background:#0f0f11;border:1px solid #353540;border-radius:3px;padding:3px 6px;color:#e8e8f0;font-size:11px;box-sizing:border-box;width:100%';
      inp.value=String(val||'');
      row.appendChild(lbl);
      row.appendChild(inp);
      return row;
    }
    var src=meta.source||'unknown';
    var srcColor=src==='ads'?'#7ef7c2':src.startsWith('ads')?'#f7c97e':'#888';
    body.innerHTML='';
    body.appendChild(fld('Title','__bm_t__',meta.title||''));
    body.appendChild(fld('Authors','__bm_a__',meta.authors||''));
    body.appendChild(fld('Year','__bm_y__',meta.year||''));
    body.appendChild(fld('Journal','__bm_j__',meta.journal||''));
    body.appendChild(fld('Volume','__bm_v__',meta.volume||''));
    body.appendChild(fld('Pages','__bm_p__',meta.pages||''));
    body.appendChild(fld('DOI','__bm_d__',meta.doi||''));
    body.appendChild(fld('arXiv ID','__bm_x__',meta.arxiv_id||''));
    ov.dataset.bibcode=meta.bibcode||'';
    ov.dataset.bibkey=meta.bibkey||'';
    ov.dataset.identifiers=JSON.stringify(meta.identifiers||[]);
    var libRow=document.createElement('div');
    libRow.style.cssText='display:flex;align-items:center;margin-bottom:8px;margin-top:6px;gap:6px;background:rgba(126,184,247,0.08);border:1px solid rgba(126,184,247,0.3);border-radius:4px;padding:4px 6px';
    var libLbl=document.createElement('div');
    libLbl.style.cssText='font-size:9px;color:#7eb8f7;text-transform:uppercase;letter-spacing:.1em;width:58px;flex-shrink:0;text-align:right;font-weight:600';
    libLbl.textContent='Library';
    var libSel=document.createElement('select');
    libSel.id='__bm_lib__';
    libSel.style.cssText='flex:1;background:#0f0f11;border:1px solid #353540;border-radius:3px;padding:3px 6px;color:#e8e8f0;font-size:11px;box-sizing:border-box';
    libRow.appendChild(libLbl);
    libRow.appendChild(libSel);
    body.appendChild(libRow);
    var dashLink=document.createElement('div');
    dashLink.style.cssText='font-size:10px;color:#555;margin-bottom:6px;margin-top:2px';
    dashLink.innerHTML='Other functions: <a href="'+dashboard+'" target="_blank" style="color:#7eb8f7">BibMan Dashboard</a>';
    body.appendChild(dashLink);
    var srcDiv=document.createElement('div');
    srcDiv.style.cssText='font-size:10px;margin-bottom:10px';
    srcDiv.innerHTML='Source: <span style="color:'+srcColor+'">'+src+'</span>';
    body.appendChild(srcDiv);
    var btnRow=document.createElement('div');
    btnRow.style.cssText='display:flex;gap:8px;justify-content:flex-end';
    var canBtn=document.createElement('button');
    canBtn.id='__bm_can__';
    canBtn.textContent='Cancel';
    canBtn.style.cssText='padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer';
    canBtn.onclick=function(){ov.remove();};
    var savBtn=document.createElement('button');
    savBtn.id='__bm_sav__';
    savBtn.textContent='Add to BibMan';
    savBtn.disabled=true;
    savBtn.style.cssText='padding:5px 14px;background:#7eb8f7;border:none;color:#000;border-radius:4px;cursor:pointer;font-weight:600;opacity:0.5';
    btnRow.appendChild(canBtn);
    btnRow.appendChild(savBtn);
    body.appendChild(btnRow);
    // Fetch libraries in parallel while user reviews metadata
    fetch(u,{method:'POST',headers:{'Content-Type':'text/plain'},
      body:JSON.stringify({credential:c,action:'get_libraries'})})
    .then(function(r){return r.json();})
    .then(function(ld){
      _maybeShowUpdateNotice(ld);
      if(!ld.libraries||!ld.libraries.length){
        libSel.innerHTML='';
        var o=document.createElement('option');
        o.value='';o.textContent='Default library';
        libSel.appendChild(o);
      }else{
        libSel.innerHTML='';
        ld.libraries.forEach(function(l){
          var o=document.createElement('option');
          o.value=l.name;o.textContent=l.name;
          if(l.name===ld.current)o.selected=true;
          libSel.appendChild(o);
        });
      }
      var newOpt=document.createElement('option');
      newOpt.value='__db__';newOpt.textContent='+ New (use Dashboard)';
      libSel.appendChild(newOpt);
      savBtn.disabled=false;
      savBtn.style.opacity='1';
    })
    .catch(function(){
      libSel.innerHTML='';
      var o=document.createElement('option');
      o.value='';o.textContent='Default library';
      libSel.appendChild(o);
      savBtn.disabled=false;
      savBtn.style.opacity='1';
    });
    savBtn.onclick=function(){
      savBtn.textContent='Saving...';savBtn.disabled=true;
      var lv=libSel.value==='__db__'?'':libSel.value;
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
          bibcode:ov.dataset.bibcode||'',
          bibkey:ov.dataset.bibkey||'',
          identifiers:JSON.parse(ov.dataset.identifiers||'[]'),
          library:lv,
          _username:localStorage.getItem('bibman_u_'+c.substring(0,8))||''
        })
      })
      .then(function(r){return r.json();})
      .then(function(result){
        _maybeShowUpdateNotice(result);
        var body2=document.getElementById('__bm_body__');
        if(result.error){
          body2.innerHTML='';
          var ed2=document.createElement('div');
          ed2.style.cssText='color:#f77e7e';
          ed2.textContent=result.error;
          var cb2=document.createElement('button');
          cb2.textContent='Close';
          cb2.style.cssText='margin-top:10px;padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer';
          cb2.onclick=function(){ov.remove();};
          body2.appendChild(ed2);
          body2.appendChild(cb2);
        }else{
          body2.innerHTML='';
          var ok=document.createElement('div');
          ok.style.cssText='color:#7ef7c2;text-align:center;padding:16px';
          ok.textContent='Added: '+(result.bibkey||result.message||'done');
          body2.appendChild(ok);
          setTimeout(function(){ov.remove();},2000);
        }
      })
      .catch(function(e){
        var body2=document.getElementById('__bm_body__');
        if(!body2)return;
        body2.innerHTML='';
        var ok=document.createElement('div');
        ok.style.cssText='color:#f7c97e;text-align:center;padding:16px;font-size:11px';
        ok.textContent='Request sent — check BibMan dashboard to confirm paper was added.';
        body2.appendChild(ok);
        setTimeout(function(){ov.remove();},3000);
      });
    };
  })
  .catch(function(e){
    var body=document.getElementById('__bm_body__');
    if(!body)return;
    var msg=e.message||'unknown error';
    var isPdf=url.indexOf('.pdf')>-1;
    var isCors=msg.indexOf('fetch')>-1||msg.indexOf('CORS')>-1;
    body.innerHTML='';
    if(isCors&&isPdf){
      var pd=document.createElement('div');
      pd.style.cssText='color:#f7c97e;margin-bottom:8px';
      pd.textContent='Raw PDF page - please go to the abstract page and try again.';
      var pcb=document.createElement('button');
      pcb.textContent='Close';
      pcb.style.cssText='padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer';
      pcb.onclick=function(){ov.remove();};
      var pwr=document.createElement('div');
      pwr.style.cssText='text-align:right;margin-top:8px';
      pwr.appendChild(pcb);
      body.appendChild(pd);
      body.appendChild(pwr);
    }else{
      var ed=document.createElement('div');
      ed.style.cssText='color:#f77e7e';
      ed.textContent='Error: '+msg;
      var ecb=document.createElement('button');
      ecb.textContent='Close';
      ecb.style.cssText='margin-top:10px;padding:5px 14px;background:transparent;border:1px solid #353540;color:#888;border-radius:4px;cursor:pointer';
      ecb.onclick=function(){ov.remove();};
      body.appendChild(ed);
      body.appendChild(ecb);
    }
  });
})();
