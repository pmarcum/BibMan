(function(){
  // The bookmarklet's own number: raise it, and bibman_bookmarklet_version in version.json, whenever this file changes,
  // so older bookmarklets are told to get the new one (MAINTENANCE.md, "The bookmarklet")
  var bv=1;
  var u='__GAS_URL__';
  var c='__CREDENTIAL__';
  var who='__USERNAME__';if(who.indexOf('__')===0)who='';
  // A guest bookmarklet (Core 12) carries only its guest key: the key decides the library and the name
  var g='__GUEST_KEY__';if(g.indexOf('__')===0)g='';
  var url=window.location.href;
  var identifier=null;
  // arXiv numbers, new (2101.00374) and old (astro-ph/0701517, math.GT/0309136) forms
  var m=url.match(/arxiv\.org\/(?:pdf|abs|html)\/(\d{4}\.\d{4,5}|[a-z][a-z\-]*(?:\.[A-Za-z]{2})?\/\d{7})/i);
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
  // The form opens in BibMan's own window (Core 19), not on the page: sites with a strict Content Security Policy
  // (SciX) refuse a page's requests to BibMan, but not a new window. The details go after the #, which browsers never
  // send to a server; the window reads them and then removes them from its address.
  var d={bv:bv,url:url,identifier:identifier||'',title:document.title||'',who:who};
  if(g)d.guest_key=g;else d.credential=c;
  var h=btoa(unescape(encodeURIComponent(JSON.stringify(d)))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  var w=480,ht=580;
  var left=Math.max(0,(window.screenX||0)+(window.outerWidth||w)-w-20),top=(window.screenY||0)+70;
  var win=window.open(u+'?capture=1&t='+Date.now()+'#'+h,'bibman_capture','popup,width='+w+',height='+ht+',left='+left+',top='+top);
  if(!win)alert('BibMan: the browser blocked BibMan\'s window. Allow pop-ups for this site, then click the bookmarklet again.');
  else try{win.focus();}catch(e){}
})();
