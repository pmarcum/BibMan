// OVERVIEW: 
// This code generates an ASCII file of bibtex entries that can be used as the .bib file for a latex document. The code
// also provides a customized pdf-viewer that allows annotations that can be tagged independently of the paper as a whole. 
// The code provides a search engine that allows the user to retrieve those tagged items using simple to complex search queries. 

///////////////////////////////////////// getConstants //////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////
function getConstants(){
   var adsBibtexUrl = "https://api.adsabs.harvard.edu/v1/export/bibtex/INSERTADSID";
   var adsLinksUrl = "https://api.adsabs.harvard.edu/v1/resolver/INSERTADSID/esource";
   var urls = {"ads":{"bibtex":adsBibtexUrl, "links":adsLinksUrl}};
   var maxTagLevels = 6;
   var hidePopupAfterThisManySeconds = 5;
   var maxBatchSize = 10;
   var startWithThisManyRows = 10;
   var waitThisManySeconds = 10 * 1000 // microseconds 
   var maxMinutesOfExecution = 4.0 * 60 * 1000 // microseconds
   var busyColor = "#ff0000";
   var finishedColor = "#1c4587";
   var colors = {"busy":busyColor, "finished":finishedColor};
   var windowWidth = 5000; // pixels, but big enough so that the browser will adjust as needed (e.g., browser will shrink if needed)
   var windowHeight = 7000;
   var windowSize = {"width": windowWidth, "height":windowHeight};
   var duplicateSymbol = "🇩";
   var noInfoSymbol = "❓";
   var hasBeenTaggedSymbol = "🔖";
   var insufficientInfoSymbol = "🛈";
   var hasCommentsSymbol = "💬";
   var isOK = "☑";
   var brokenLink = "🔗";
   var symbols = {"duplicate":duplicateSymbol,"noInfo":noInfoSymbol,"insufficientInfo":insufficientInfoSymbol,"brokenLink":brokenLink,"isOK":isOK,
                  "hasComments":hasCommentsSymbol,"hasBeenTagged":hasBeenTaggedSymbol};
   var ssId = SpreadsheetApp.getActiveSpreadsheet().getId();
   var folderId = DriveApp.getFileById(ssId).getParents().next().getId();
   var bibtexSheetName = 'PDF FILE LIST';
   var searchPageSheetName = 'TAG SEARCH';
   var folderInfoSheetName = 'FOLDER INFO';
   var tagDictionary= 'TAG DICTIONARY';
   var sheetNames = {"bibtex":bibtexSheetName, "search":searchPageSheetName, "folderInfo":folderInfoSheetName, "tagDictionary":tagDictionary};
   var searchTagWordsEqn = 'IFS(TRIM(INDEX(tagPathname,ROW()-ROW(tagPathname)+1))="","",REGEXMATCH(TRIM(INDEX(tagPathname,ROW()-ROW(tagPathname)+1)),"->"),"|" & '+
                           'TRIM(JOIN("|",SORT(UNIQUE(TRANSPOSE(ARRAYFORMULA(TRIM(SPLIT(REGEXREPLACE(TRIM(INDEX(tagPathname,ROW()-ROW(tagPathname)+1,1)),"->","|"),"|")))),1,TRUE)))) & '+
                           '"|",TRIM(INDEX(tagPathname,ROW()-ROW(tagPathname)+1))<>"","|" & TRIM(INDEX(tagPathname,ROW()-ROW(tagPathname)+1,1)) & "|")';
   var fullTagPathnameEqn = 'JOIN("|",ARRAYFORMULA(VLOOKUP(TRANSPOSE(SPLIT(INDEX(searchtagIds,ROW()-ROW(searchtagIds)+1,1),"|",FALSE,TRUE)),{tagId,tagDictionary},2,FALSE)))';
   var formulas = {"searchTagWords":searchTagWordsEqn, "fullTagPathname":fullTagPathnameEqn};
   var tokensheet = SpreadsheetApp.getActive().getSheetByName('NASA ADS TOKENS');
   var tokens = tokensheet.getRange('tokens').getValues();
   var tokeninfo = {};
   for (let token of tokens){tokeninfo[token[0]] = token[1];}
   var consts = {
     "folderId":folderId,"symbols":symbols,"colors":colors, "windowSize":windowSize, "urls":urls, "maxTagLevels":maxTagLevels, "tokens":tokeninfo,
     "startWithThisManyRows":startWithThisManyRows, "waitThisManySeconds":waitThisManySeconds,"maxMinutesOfExecution":maxMinutesOfExecution, 
     "maxBatchSize":maxBatchSize, "sheetNames":sheetNames, "hidePopupAfterThisManySeconds":hidePopupAfterThisManySeconds, "formulas":formulas};
   // stick these values into the memory:
   var nHours = 1;
   deleteCacheChunks("consts");
   putCacheChunks(JSON.stringify(consts), "consts", nHours * 60);
}

////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////  onOpen ///////////////////////////////////////////////
function onOpen(e) {
  // load up the constants into the cache
  SpreadsheetApp.getUi()
                .createMenu('📚-LIBRARY FUNCTIONS-📚')
                .addSeparator()
                .addSeparator()
                .addItem('👀-DISPLAY the PDF selected in spreadsheet-👀', 'displayPdf')
                .addSeparator()
                .addSeparator()
                .addItem('🕵️-SEARCH for topics-🕵️','searchForTopics')
                .addSeparator()
                .addSeparator()
                .addItem('📜-UPDATE LIBRARY (process recent changes to PDF Library and update Bib File)-📜', 'getToBeProcessedIds')
                .addSeparator()
                .addSeparator()
                .addToUi();
}
////////////////////////////////////////  onOpen ///////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////  getTagLibrary ////////////////////////////////////////////
function getTagLibrary(){
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var sheetNames = consts.sheetNames;
   var tagDictSheet = SpreadsheetApp.getActive().getSheetByName(sheetNames.tagDictionary);
   var tagLibrary = {};
   var tagNames = tagDictSheet.getRange('tagDictionary').getValues().map(z => z[0].trim());
   var tagIDs = tagDictSheet.getRange('tagId').getDisplayValues().map(z => z[0].trim());
   tagNames = tagNames.map(function(z,k){if(tagIDs[k] != '' && z != ''){return z;} else {return '';}});
   tagIDs = tagIDs.map(function(z,k){if(tagNames[k] != '' && z != ''){return z;} else {return '';}});
   tagNames = tagNames.filter(z => z != '');
   tagIDs = tagIDs.filter(z => z != '');
   var sortedTagNames = ([... new Set(tagNames)]).sort();
   var newTagIdList = [];
   for (let i in sortedTagNames){
       var indx = tagNames.indexOf(sortedTagNames[i]);
       var displayName = sortedTagNames[i].split("\-\>").reverse()[0];
       var nLevel = sortedTagNames[i].split("\-\>").length;
       tagLibrary[sortedTagNames[i]] = {"tagId":tagIDs[indx]};
       tagLibrary[tagIDs[indx]] = {
          "fullName":sortedTagNames[i],"displayName":displayName,"level":nLevel,"parentTagId":'',"level1ParentId":'',"isSubMenu":false,"edited":false};
       if (nLevel == 1){tagLibrary[tagIDs[indx]].isSubMenu = true;}
       newTagIdList.push(tagIDs[indx]);
   }
   for (let tagId of tagIDs){
       var parentTagName = '';
       if (tagLibrary[tagId].level > 1){
           var parentTagName = tagLibrary[tagId].fullName.split("\-\>").slice(0,tagLibrary[tagId].level-1).join("\-\>"); 
           var parentTagId = tagLibrary[parentTagName].tagId;
           tagLibrary[parentTagId].isSubMenu = true;
           tagLibrary[tagId].parentTagId = parentTagId;
           var level1TagName = tagLibrary[tagId].fullName.split("\-\>")[0];
           var level1Id = tagLibrary[level1TagName].tagId;
           tagLibrary[tagId].level1ParentId = level1Id;
       }
   }
   tagLibrary.tagNameList = sortedTagNames;
   tagLibrary.tagIdList = newTagIdList;
   return tagLibrary;
}
////////////////////////////////////// getTagLibrary ///////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////// makeTopicTree /////////////////////////////////////////
function makeTopicTree(){
   var spreadsheetInfo = {};
   // This function is called by searchForTopics.html
   var tagLibrary = getTagLibrary();
   var tagIdList = tagLibrary.tagIdList;
   //
   // Gather up the other information regarding comments and paper sources needed to construct results from search queries.  Gather up all items
   // that have been tagged (papers as a whole and comments within papers but which are considered as independent entities)
   var topicIds = SpreadsheetApp.getActiveSpreadsheet().getRange("searchtagIds").getDisplayValues().map(z => z[0].trim());
   var commentCoords = SpreadsheetApp.getActiveSpreadsheet().getRange("searchCommentCoords").getDisplayValues().map(z => z[0].trim());
   var quotes = SpreadsheetApp.getActiveSpreadsheet().getRange("quote").getDisplayValues().map(z => z[0].trim());
   var paperCommentIds = SpreadsheetApp.getActiveSpreadsheet().getRange("pcId").getDisplayValues().map(z => z[0].trim());
   var paperIds = SpreadsheetApp.getActiveSpreadsheet().getRange("pId").getDisplayValues().map(z => z[0].trim());
   var bibkeys = SpreadsheetApp.getActiveSpreadsheet().getRange("source").getDisplayValues().map(z => z[0].trim());
   var paperOrComment = SpreadsheetApp.getActiveSpreadsheet().getRange("paperOrComment").getDisplayValues().map(z => z[0].trim());
   //
   var fileIds = SpreadsheetApp.getActiveSpreadsheet().getRange("fileId").getDisplayValues().map(z => z[0].trim());
   var paperUrls = SpreadsheetApp.getActiveSpreadsheet().getRange("bibPdfUrl").getDisplayValues().map(z => z[0].trim());
   var maxrow = -1;
   for (let i=0; i<paperIds.length; i++){if (paperIds[i].trim() != ''){maxrow = i;}}
   if (maxrow > -1){
       maxrow = maxrow + 1;
       topicIds = topicIds.slice(0,maxrow);
       commentCoords = commentCoords.slice(0,maxrow);
       quotes = quotes.slice(0,maxrow);
       paperIds = paperIds.slice(0,maxrow);
       paperCommentIds = paperCommentIds.slice(0,maxrow);
       bibkeys = bibkeys.slice(0,maxrow);
       paperOrComment = paperOrComment.slice(0,maxrow);
   } 
   var maxrow = -1;
   for (let i=0; i<fileIds.length; i++){if (fileIds[i].trim() != ''){maxrow = i;}}   
   maxrow = maxrow + 1;
   fileIds = fileIds.slice(0,maxrow);
   paperUrls = paperUrls.slice(0,maxrow);
   var forUpsetPlot = {"paperCommentList":paperCommentIds};
   var tree = [{"id":"root"}];
   var treeTopicIdList = [];
   for (let i=0; i<paperCommentIds.length; i++){
       var thisPaperCommentId = paperCommentIds[i];
       forUpsetPlot[thisPaperCommentId] = {"taggedTopics":[], "entry":''};
       var thisTopicList = [];
       for (let thisTopicId of topicIds[i].split("|")){
           var tlist = tagLibrary[thisTopicId].fullName.trim().split("\-\>").map(z => z.trim().replace(/  +/g," ").replace(/ /g,"\_").trim());
           for (let j=0; j<tlist.length; j++){if (tlist[j].charAt(0) != "\~"){thisTopicList.push(tlist[j]);}}
           var thisTreeEntry = {};
           var fullName = tagLibrary[thisTopicId].fullName.trim();
           while (fullName.length > 0){
               var tmpId = tagLibrary[fullName].tagId;
               if (treeTopicIdList.indexOf(tmpId) == -1){
                   var displayname = tagLibrary[tmpId].displayName.trim().replace(/  +/g," ").replace(/ /g,"\_");
                   if (tagLibrary[tmpId].level == 1){
                       thisTreeEntry = {"id":tmpId, "parent":"root", "name":displayname};
                   } else {
                       thisTreeEntry = {"id":tmpId, "parent":tagLibrary[tmpId].parentTagId, "name":displayname};
                   }
                   tree.push(thisTreeEntry);
                   treeTopicIdList.push(tmpId);
               }
               fullName = fullName.split(/\-\>/);
               var num = fullName.length;
               if (num > 1){
                   fullName = fullName.slice(0,num-1).join("\-\>");
               } else {
                   fullName = '';
               }
           }    
       }
       thisTopicList = ([... new Set(thisTopicList)]).sort();
       forUpsetPlot[thisPaperCommentId].taggedTopics = thisTopicList;
       // now put the information together.  Wrap the url around the bibkey, append the title or quote. 
       var indx = fileIds.indexOf(paperIds[i]);
       var linkedBibkey = '<a href="' + paperUrls[indx] + '">' + bibkeys[i] + '</a>';
       var thisPage = '';
       if (paperOrComment[i] == 'C'){
           thisPage = commentCoords[i].split('x')[0].replace("p","").trim();
       }
       var thisEntry = '<tr><td>' + linkedBibkey + '</td><td><textarea>' + quotes[i] + '</textarea></td><td>';
       thisEntry = thisEntry + thisPage + '</td></tr>';
       forUpsetPlot[thisPaperCommentId].entry = thisEntry;
   }
   spreadsheetInfo.forUpsetPlot = forUpsetPlot;
   // now put together the "tree" menu, only showing topics that are associated with tagged papers:
   spreadsheetInfo.topicTree = tree;
   return JSON.stringify(spreadsheetInfo);
}
///////////////////////////////// makeTopicTree /////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////

///////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////// getToBeProcessedIds /////////////////////////////////////////
function getToBeProcessedIds() {
   var startTime = (new Date()).getTime();
   // read in the spreadsheet and look for any rows for which the ID number is defined in the PDF FILE LIST 
   // column but having no status in the status column.  Those entries are either brand new (added by the user), 
   // or are entries that were manually modified by the user and the status was removed so that the entries could 
   // be re-processed.  
   deleteCacheChunks("consts");
   deleteCacheChunks("toBeProcessed");
   getConstants();
   var consts = JSON.parse(getCacheChunks("consts"));
   var sheetNames = consts.sheetNames;
   var bibsheet = SpreadsheetApp.getActive().getSheetByName(sheetNames.bibtex);
   // read in the status and the file id columns: 
   var status = bibsheet.getRange("bibStatus").getValues().map(z => z[0]);
   var fileIds = bibsheet.getRange("fileId").getDisplayValues().map(z => z[0]);
   var toBeProcessedIds = fileIds.map(function(z,k){if (z && status[k].trim() == '' && z.trim() != ''){return z.trim();} else {return '';}});
   toBeProcessedIds = toBeProcessedIds.filter(z => z != '');
   // Now that we have the list of ids that need to be worked on, let's put this list into memory/storage cache and pass along to next function
   putCacheChunks(JSON.stringify({"toBeProcessedIds":toBeProcessedIds, "startTime":startTime, "updateAscii":false}),'toBeProcessedIds');
   processTheEntries();
}
///////////////////////////////// getToBeProcessedIds /////////////////////////////////////////
///////////////////////////////////////////////////////////////////////////////////////////////

///////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////// processTheEntries //////////////////////////////////////
function processTheEntries(){
   var storedInfo = JSON.parse(getCacheChunks('toBeProcessedIds'));
   var startTime = storedInfo.startTime;
   var updateAscii = storedInfo.updateAscii;
   if (startTime == -1){startTime = (new Date()).getTime();}
   SpreadsheetApp.getActiveSpreadsheet().toast('.... gathering entries in pdf library to be processed ....', '⏰  ... busy ... ⏰', 6*60);
   var toBeProcessedIds = storedInfo.toBeProcessedIds;
   var triggers = ScriptApp.getProjectTriggers();
   for (var i=0; i < triggers.length; i++) {if (triggers[i].getEventType() == ScriptApp.EventType.CLOCK){ScriptApp.deleteTrigger(triggers[i]);}}
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var sheetNames = consts.sheetNames;
   var symbols = consts.symbols;
   var maxMinutesOfExecution = consts.maxMinutesOfExecution;
   var waitThisManySeconds = consts.waitThisManySeconds;
   var maxBatchSize = consts.maxBatchSize;
   var outOfTime = false;
   var maxTimePerBatch = -1;
   var maxTimePerFile = -1;
   var bibsheet = SpreadsheetApp.getActive().getSheetByName(sheetNames.bibtex);
   var statusCol = bibsheet.getRange('bibStatus').getColumn();
   var col1 = bibsheet.getRange('bibUpperLeft').getColumn();
   var row1 = bibsheet.getRange('bibUpperLeft').getRow();
   var col2 = bibsheet.getRange('bibUpperRight').getColumn();
   var pdfUrlCol = bibsheet.getRange('bibPdfUrl').getColumn();
   var bibtexCol = bibsheet.getRange('bibtex').getColumn();
   var row2 = bibsheet.getLastRow();
   var allEntries = bibsheet.getRange(row1,col1-1,row2-row1+1,2).getValues(); // status and bibkey
   allEntries = allEntries.filter(z => z[0]==symbols.isOK);
   // go through each ID, one by one, and determine what information needs to be added to the sheet in order to make the entry fully processed.
   // As you go through each entry, remove the id from the list until you reach the end and no more IDs to process. 
   while (toBeProcessedIds && toBeProcessedIds.length > 0 && (!(outOfTime))){
      var t1 = (new Date()).getTime();
      var pdfId = toBeProcessedIds[0].trim();
      SpreadsheetApp.getActiveSpreadsheet().toast('.... processing file '+pdfId+' ....', '⏰  ... busy ... ⏰', 6*60);
      // figure out which row this ID corresponds to and get all the available info on it that is in the sheet
      var allIds = bibsheet.getRange('fileId').getDisplayValues().map(z => z[0].trim());
      var thisRowIndx = allIds.indexOf(pdfId) + Number(row1);
      var thisPdfUrl = bibsheet.getRange(thisRowIndx,pdfUrlCol).getValue();
      var thisBibtex = bibsheet.getRange(thisRowIndx,bibtexCol).getValue();
      // determine if the id is a google drive file Id or a NASA ADS bibcode:
      var idType = getSourceType(pdfId);     
      if (pdfId.match(/\.\.\./)){idType = "ads";} // the previous .match("...") made idType = 'ads' for everything. Not sure why.
      if (idType == "ads"){
          // retrieve the NASA ADS-provided bibtex and pdf url link
          var adsInfo = getInfoFromADS(pdfId);
          // if the bibtex is missing from the sheet, insert the ads bibtex in now
          if (thisBibtex.trim() == '' || thisBibtex.match(/error/)){thisBibtex = adsInfo.bibtex;}
          // if the pdf link is missing, use the one provided by the ads
          if (thisPdfUrl.trim() == '' || thisPdfUrl.match(/error/)){thisPdfUrl = adsInfo.pdfUrl;}
       } else {
          // turn the google id into a google drive file url that can be placed into the spreadsheet
          if (thisPdfUrl.trim() == '' || thisPdfUrl.match(/error/)){thisPdfUrl = DriveApp.getFileById(pdfId).getUrl();}
       }
       // Now examine the bibtex and make sure that it has everything that it needs: 
       // (first, remove any fields that say "missing" in the current bibtex version)
       thisBibtex = thisBibtex.split('\n').filter(z => !(z.match(/\{missing\}/))).join('\n');
       var bibInfo = getBibInfo(thisBibtex);
       thisBibtex = bibInfo.bibtex;
       var thisBibkey = bibInfo.bibkey;
       var thisTitle = getTitle(thisBibtex);
       // Is this file redundant with an existing entry? 
       var status = '';
       if (allEntries.map(z => z[1]).indexOf(thisBibkey) != -1){status = 'DUP';}
       // is the bibtex missing needed information? 
       if (thisBibtex.match(/\{missing\}/)){status = 'INSUFF';}
       // is the bibtex missing altogether? 
       if (thisBibtex.trim() == ''){status = 'MISS';}
       // add the status to the bibkey:
       thisBibkey = thisBibkey + status;
       // now write this info into the sheet
       // do a quick check to make sure that we know the location of this entry (in case someone may have edited while we wer doing the above)
       var allIds = bibsheet.getRange('fileId').getDisplayValues().map(z => z[0].trim());
       var statuses = bibsheet.getRange('bibStatus').getValues().map(z => z[0]);
       // if the file Id is a NASA ADS bibcode rather than a google file ID, then there could hypothetically be multiple occurances of the 
       // same NASA ADS bibcode.  Look up all of them:
       var theseRowIndx = allIds.map(function(z,k){if (z==pdfId && (!(statuses[k])||(statuses[k]===undefined)||(statuses[k]===null)||(statuses[k].trim()==''))){
          return Number(k)+Number(row1);} else {return -1;}}).filter(z => z != -1);
       theseRowIndx = theseRowIndx.sort();
       // if the status is equal to '', means that the bibtex is ok and not missing any info and not duplicative with any previously-processed entry.
       // so set the first of the "theseRowIndx" to a status of '' (which will translate as a checked green box in the spreadsheet), but all others
       // to a "DUP", if there are more than 1 item within theseRowIndx:
       var entry = makePdfFileListEntry({"pdfId":pdfId, "bibkey":thisBibkey, "title":thisTitle, "bibtex":thisBibtex, "url":thisPdfUrl}); 
       var formatRange = bibsheet.getRange(row1+1,col1,1,entry.length);
       bibsheet.getRange(theseRowIndx[0],col1,1,entry.length).setValues([entry]);
       // make sure the format of the row is consistent with the ones above it
       // get a row for the format
       var thisRange = bibsheet.getRange(theseRowIndx[0],col1,1,entry.length);
       formatRange.copyTo(thisRange, {formatOnly:true});
       if (status == ''){
           status = 'DUP';
           thisBibkey = thisBibkey + status;
           entry = makePdfFileListEntry({"pdfId":pdfId, "bibkey":thisBibkey, "title":thisTitle, "bibtex":thisBibtex, "url":thisPdfUrl}); 
       }
       for (let k=1; k<theseRowIndx.length; k++){
           var thisRowIndx = theseRowIndx[k];
           bibsheet.getRange(thisRowIndx,col1,1,entry.length).setValues([entry]);
           thisRange = bibsheet.getRange(thisRowIndx,col1,1,entry.length);
           formatRange.copyTo(thisRange, {formatOnly:true});
       }
       if (toBeProcessedIds.length > 1){toBeProcessedIds = toBeProcessedIds.slice(1);} else {toBeProcessedIds = [];}
       var t2 = (new Date()).getTime();
       if (maxTimePerFile==-1){maxTimePerFile=Number(t2)-Number(t1);} else if ((Number(t2)-Number(t1))>maxTimePerFile){maxTimePerFile=(Number(t2)-Number(t1));}
       if (((new Date()).getTime() - Number(startTime) + Number(maxTimePerFile)) > maxMinutesOfExecution){outOfTime = true;}
       updateAscii = true;
   }
   if (toBeProcessedIds.length == 0 && updateAscii && (((new Date()).getTime() - Number(startTime) + Number(maxTimePerFile)) > 0.5*maxMinutesOfExecution)){outOfTime = true;}
   if (outOfTime){
      // ran out of time, need to spin up a new process. save what we have in the storage area:
      SpreadsheetApp.getActiveSpreadsheet().toast('.... still processing files; ran out of time ... saving info in storage ....', '⏰  ... busy ... ⏰', 6*60);
      putCacheChunks(JSON.stringify({"toBeProcessedIds":toBeProcessedIds, "startTime":-1, "updateAscii":updateAscii}), "toBeProcessedIds");
      SpreadsheetApp.getActiveSpreadsheet().toast('.... kicking off new processTheEntries ....', '⏰  ... busy ... ⏰', 6*60);
      var triggers = ScriptApp.getProjectTriggers();
      for (var i=0; i < triggers.length; i++) {if (triggers[i].getEventType() == ScriptApp.EventType.CLOCK){ScriptApp.deleteTrigger(triggers[i]);}}
      ScriptApp.newTrigger("processTheEntries").timeBased().at(new Date((new Date().getTime()) + waitThisManySeconds)).create();
      return; // ================== return 
   }
   SpreadsheetApp.getActiveSpreadsheet().toast('.... You may now select another task ....', '🎉  ... FINISHED WITH PDF LIBRARY UPDATE ... 🎉', 30);
   deleteCacheChunks("toBeProcessedIds");
   // if anything changed about the bibtex, then neeed to update the ascii "bibfile.txt" file
   if (updateAscii){
      SpreadsheetApp.getActiveSpreadsheet().toast('.... writing new bibtex text file ....', '⏰  ... busy ... ⏰', 10);
      console.log('finished processing all files in the folder; now writing ascii file');
      writeAsciiFile();
      SpreadsheetApp.getActiveSpreadsheet().toast('.... You may now select another task ....', '🎉  ... FINISHED WITH PDF LIBRARY UPDATE ... 🎉', 10);
   }
   return;
}
////////////////////////////////// processTheEntries ////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////// putCacheChunks //////////////////////////////////////////////
function putCacheChunks(str,key,timeout,lim,exp) {
  // delete any existing cache
  deleteCacheChunks("key");
  if (timeout){var nSeconds = timeout * 60;} else {nSeconds = 30 * 60;} // default to 10 minutes
  var cache = CacheService.getUserCache();
  if(lim === undefined){lim = 100000;} 
  if(exp === undefined){exp = ''} else{exp = ',' + exp;}
  var len = str.length;  
  var num = Math.floor(len/lim);
  var chunk = '';
  if(num == 0){
    cache.put(key,str,nSeconds);
  } else {
    for(var a = 0; a<=num; a++){
       if(a == 0){cache.put(key + '_idx',num + exp);}
       chunk = str.slice(lim * a,lim * (a+1)); 
       cache.put(key + "_" + a , chunk +exp, nSeconds);
    }
  }
}
/////////////////////////////////// putCacheChunks //////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////// getCacheChunks //////////////////////////////////////////////
function getCacheChunks(key){
  var cache  = CacheService.getUserCache();
  var solo = cache.get(key);
  var str = '';
  if (solo && solo !== null){
     str = solo;
  } else {
     var num = cache.get(key + '_idx');
     if(!num){return '';}
     for (var a = 0; a<=num; a++){if (cache.get(key + '_' + a) && cache.get(key + '_' + a) !== null){str += cache.get(key + '_' + a);}}
  }
  try {
     var obj = JSON.parse(str);
     if (!(str) || str===null || str.replace(/null/g,"").trim() == "" || str.replace(/ /g,"").trim() == ""){str = '';}
     return str;
  } catch(err){return str;}
}
/////////////////////////////////// getCacheChunks //////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////// deleteCacheChunks ////////////////////////////////////////////
function deleteCacheChunks(key){
   var cache = CacheService.getUserCache();
   var solo = cache.get(key);
   if (solo){
      cache.remove(key);
   } else {
      var num = cache.get(key + '_idx');
      if (!num){return;}
      for (var a = 0; a <= num; a++){cache.remove(key + '_' + a);}
      cache.remove(key + '_idx');
   }
}
////////////////////////////////// deleteCacheChunks ////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////// makeCommentSearchEntry //////////////////////////////////
function makeCommentSearchEntry(pdfId, commentId, storedInfo){   
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var sheetNames = consts.sheetNames;
   var formulas = consts.formulas;
   var searchTagWordEqn = formulas.searchTagWords;
   var fullTagPathnameEqn = formulas.fullTagPathname;
   if ((storedInfo[commentId].tagIdList.length==0) || ((storedInfo[commentId].quote.trim()=='') && (storedInfo[commentId].usernote.trim()==''))){return [];}
   var tagsheet = SpreadsheetApp.getActive().getSheetByName(sheetNames.search);
   var quote1Col = tagsheet.getRange('quote').getColumn();
   var quote2Col = tagsheet.getRange('quote').getLastColumn();
   var usernote1Col = tagsheet.getRange('usernote').getColumn();
   var usernote2Col = tagsheet.getRange('usernote').getLastColumn();
   var source = '=HYPERLINK("' + storedInfo.url + '";"' + storedInfo.bibkey  + '")';
   var entry = [pdfId, commentId, source, storedInfo[commentId].quote];
   var numBlanks = quote2Col - quote1Col + 1 - 1;
   for (let k=0; k<numBlanks; k++){entry.push("");} 
   // the above is putting in the blanks for the columns that are merged together under the quotes column; 1 of the columns must be substracted
   // because it is the left most column of this area and is already accounted for by being the column that actually gets written
   // into (and therefore should not be blanked out). 
   entry.push(storedInfo[commentId].usernote);
   var numBlanks = usernote2Col - usernote1Col + 1 - 1;
   for (let k=0; k<numBlanks; k++){entry.push("");} 
   var coords = storedInfo[commentId].coords.map(z =>'p'+z.p+'x'+Number(z.x1).toFixed(4)+'y'+Number(z.y1).toFixed(4)+'x'+Number(z.x2).toFixed(4)+'y'+Number(z.y2).toFixed(4));
   // the above is putting in the blanks for the columns that are merged together under the notes column;
   entry.push('='+searchTagWordEqn);
   entry.push('='+fullTagPathnameEqn);
   entry.push(storedInfo[commentId].tagIdList.join("|"));
   entry.push(coords.join("|"));
   return entry;
}
///////////////////////////// makeCommentSearchEntry ////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////// makePdfSearchEntry /////////////////////////////////////
function makePdfSearchEntry(pdfId, storedInfo){
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var sheetNames = consts.sheetNames;
   var formulas = consts.formulas;
   var searchTagWordEqn = formulas.searchTagWords;
   var fullTagPathnameEqn = formulas.fullTagPathname;
   if (storedInfo['pdf'].tagIdList.length == 0) {return [];}
   var tagsheet = SpreadsheetApp.getActive().getSheetByName(sheetNames.search);
   var quote1Col = tagsheet.getRange('quote').getColumn();
   var quote2Col = tagsheet.getRange('quote').getLastColumn();
   var usernote1Col = tagsheet.getRange('usernote').getColumn();
   var usernote2Col = tagsheet.getRange('usernote').getLastColumn();
   var source = '=HYPERLINK("' + storedInfo.url + '";"' + storedInfo.bibkey  + '")';
   var entry = [pdfId, pdfId, source, storedInfo.title];
   var numBlanks = quote2Col - quote1Col + 1 - 1;
   for (let k=0; k<numBlanks; k++){entry.push("");}
   // the above is putting in the blanks for the columns that are merged together under the quotes column; 1 of the columns must be substracted
   // because it is the left most column of this area and is already accounted for by being the column that actually gets written
   // into (and therefore should not be blanked out). 
   var numBlanks = usernote2Col - usernote1Col + 1;
   for (let k=0; k<numBlanks; k++){entry.push("");} 
   entry.push('='+searchTagWordEqn);
   entry.push('='+fullTagPathnameEqn);
   entry.push(storedInfo['pdf'].tagIdList.join("|"));
   entry.push('');
   return entry;
}
//////////////////////////////// makePdfSearchEntry /////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////// makePdfFileListEntry /////////////////////////////////////
function makePdfFileListEntry(pdfInfo){
   if (pdfInfo.url !== '' && !(pdfInfo.url.match(/error/))){
      var linkedKey = '=HYPERLINK("' + pdfInfo.url + '";"' + pdfInfo.bibkey + '")';
   } else {
      var linkedKey = pdfInfo.bibkey;
   }
   var entry = [linkedKey, pdfInfo.title, pdfInfo.bibtex, pdfInfo.pdfId, pdfInfo.url];
   return entry;
}
////////////////////////////// makePdfFileListEntry /////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////// makeTagDictionaryEntry ////////////////////////////////////
function makeTagDictionaryEntry(tagId, storedInfo){
   // Make everything but the shortname be in a grey color
   var fullTagName = storedInfo.tagLibrary[tagId].fullName;
   var shortTagName = storedInfo.tagLibrary[tagId].displayName;
   var black1 = fullTagName.length - shortTagName.length;
   var black2 = Number(black1) + Number(shortTagName.length);
   if (black1 == 0){
       var richText = 
          SpreadsheetApp.newRichTextValue()
                        .setText(fullTagName)
                        .setTextStyle(0, Number(shortTagName.length), SpreadsheetApp.newTextStyle().setBold(true).setForegroundColor("black").build())
                        .build();
   } else {
       var richText = 
          SpreadsheetApp.newRichTextValue()
                        .setText(fullTagName)
                        .setTextStyle(black1, black2, SpreadsheetApp.newTextStyle().setBold(true).setForegroundColor("black").build())
                        .setTextStyle(0, black1, SpreadsheetApp.newTextStyle().setBold(false).setForegroundColor("#b7b7b7").build())
                        .build();
   }
   //https://issuetracker.google.com/issues/36764247?pli=1#comment21
   return richText;
}
///////////////////////////////////// makeTagDictionaryEntry ////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////// writeAsciiFile ///////////////////////////////////////////
function writeAsciiFile(){
   SpreadsheetApp.getActiveSpreadsheet().toast('.... Starting to write the ASCII file for the bibfile ....', '🎉  ... BIBFILE.txt UPDATE ... 🎉', 30);
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var symbols = consts.symbols;
   var folderId = consts.folderId;
   var sheetNames = consts.sheetNames;    
   var folder = DriveApp.getFolderById(folderId);
   var files = folder.getFilesByType(MimeType.PLAIN_TEXT);
   var file;
   var bibfileId = '';
   while (files.hasNext()){
      SpreadsheetApp.getActiveSpreadsheet().toast('.... Starting to write the ASCII file for the bibfile ....', '🎉  ... BIBFILE.txt UPDATE ... 🎉', 30);
      file = files.next();
      if (file.getName().match('bibFile')){bibfileId = file.getId(); break;}
   }
   if (!(bibfileId)){
      // file does not exist, so create it
      file = folder.createFile('bibFile.txt', "", MimeType.PLAIN_TEXT);
      bibfileId = file.getId();
   }
   // read in the spreadsheet, sort, then output to text file
   var bibsheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetNames.bibtex);
   SpreadsheetApp.getActiveSpreadsheet().toast('.... Starting to write the ASCII file for the bibfile ....', '🎉  ... BIBFILE.txt UPDATE ... 🎉', 30);
   var bibkeys = bibsheet.getRange("bibkey").getValues().map(z => z[0]);
   var bibtexs = bibsheet.getRange("bibtex").getValues().map(z => z[0]);
   var bibstatus = bibsheet.getRange("bibStatus").getValues().map(z => z[0]);
   bibkeys = bibkeys.map(function(z,k){if (z.trim() != '' && bibtexs[k].trim() != '' && bibstatus[k].trim()==symbols.isOK){return z;} else {return '';}});
   bibtexs = bibtexs.map(function(z,k){if (z.trim() != '' && bibkeys[k].trim() != '' && bibstatus[k].trim()==symbols.isOK){return z;} else {return '';}});
   bibkeys = bibkeys.filter(z => z.trim() != '');
   bibtexs = bibtexs.filter(z => z.trim() != '');
   // make an array that attaches the bibkey to the front of the bibtex so that when sorted, the sort is performed on the bibkey as desired
   var keytexs = bibtexs.map(function(z,k){return (bibkeys[k] + "|||" + z)});
   // now sort
   keytexs.sort();
   // now remove the preceding bibkey
   bibtexs = keytexs.map(z => z.split("|||")[1]);
   // update file contents: 
   file = DriveApp.getFileById(bibfileId);  
   file.setContent(bibtexs.join("\n"));    
   SpreadsheetApp.getActiveSpreadsheet().toast('.... You may now select another task ....', '🎉  ... FINISHED WITH PDF LIBRARY UPDATE ... 🎉', 10);
   return;
}
////////////////////////////////////// writeAsciiFile ///////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////// getBibInfo //////////////////////////////////////////
function getBibInfo(text){
  var bibtex = "";
  var origBibtex = "";
  var bibType = "";
  var bibkey = "";
  var origBibkey = "";
  var indx1, indx2, tmp;
  if (!(text.match(/error/)) && text.trim() != "" && text.match(/\{? *\@ *[a-z]+ *\{([^\,]+) *\,\n?/i)){
     // extract the bibtex and not anything else
     if (text.match(/\{ *\@ *[a-z]+ *\{/i)){indx1 = text.indexOf("\{");} else {indx1 = text.indexOf("\@");}
     indx2 = text.lastIndexOf("\}");
     origBibtex = text.slice(indx1, indx2+1);
     bibtex = text.slice(indx1, indx2+1).trim();
     // if the bibtex began with a bracket, then remove it and make sure there is not an extra bracket at the end
     bibtex = bibtex.replace(/^ *\{/,"").trim();
     // Remove the use of quotes AND brackets in favor of brackets only
     bibtex = bibtex.replace(/\" *\{/g,"\{").replace(/\{ *\"/g,"\{").replace(/\" *\}/g,"\}").replace(/\} *\"/g,"\}").trim();
     // only 1 space before and after an equal sign.  No spaces to right of "{" and no spaces to left of "}"
     bibtex = bibtex.replace(/  +\=/g," \=").replace(/\=  +/g,"\= ");
     bibtex = bibtex.replace(/  +\{/g," \{").replace(/\{ +/g,"\{").replace(/ +\}/g,"\}").replace(/ +\,/g,"\,").trim();
     bibtex = bibtex.replace(/\" +/g,'\"').replace(/\  +\"/g,' \"');
     bibtex = bibtex.replace(/\, +\n/ig,"\,\n").replace(/  +/g," ").replace(/^\@ +/,"\@").trim();
     // make sure there is a line break after each field, and make sure that each field is indented by 1 character
     bibtex = bibtex.replace(/\,\n  +([a-z0-9]+ \= )/ig,"\,\n $1");
     bibtex = bibtex.replace(/\,\n([a-z0-9]+ \= )/ig,"\,\n $1");
     bibtex = bibtex.replace(/\,  +([a-z0-9]+ \= )/ig,"\,\n $1");
     bibtex = bibtex.replace(/\,([a-z0-9]+ \= )/i,"\,\n $1");
     // turn any quoted phrases into bracketed phrases, like titles.
     bibtex = bibtex.replace(/([a-z0-9]+ \= )\" *([^\"]+)\"/ig,"$1\{$2\}");
     // to make sure we don't have too many end-brackets, just remove all brackets and commas and spaces appearing next to the very end, then build back
     while (bibtex.match(/[\n\,\} ]$/,"")){bibtex = bibtex.replace(/[\n\,\} ]$/,"").trim();}
     var indx1 = bibtex.lastIndexOf("\{");
     var indx2 = bibtex.lastIndexOf("\}");
     if (indx2 < indx1){bibtex = bibtex + "\}";}
     bibtex = bibtex + "\n\}";
     bibType = bibtex.match(/\@([a-z]+)/i)[1].toLowerCase();
     // get the original bibkey
     origBibkey = bibtex.match(/\{? *\@[a-z]+ *\{([^\,]+)/i)[1].trim();
     var keyBib = {"key":"", "bib":bibtex};
     // parse out author and other info specific to the type of reference this is
     if (bibType=="article"){
         keyBib = getArticleInfo(keyBib);
     } else if (bibType=="book"){
         keyBib = getBookInfo(keyBib);
     } else if (bibType=="booklet"){
         keyBib = getBookletInfo(keyBib);
     } else if (bibType=="inbook"){
         keyBib = getInBookInfo(keyBib);
     } else if (bibType=="incollection"){
         keyBib = getInCollectionInfo(keyBib);
     } else if (bibType=="inproceedings" || bibType=="conference"){
         keyBib = getInProceedingsInfo(keyBib);
     } else if (bibType=="manual"){
         keyBib = getManualInfo(keyBib);
     } else if (bibType=="mastersthesis" || bibType=="phdthesis" || bibType=="thesis"){
         keyBib = getThesisInfo(keyBib);
     } else if (bibType=="misc"){
         keyBib = getMiscInfo(keyBib);
     } else if (bibType=="proceedings"){
         keyBib = getProceedingsInfo(keyBib);
     } else if (bibType=="tech report" || bibType=="techreport" || bibType=="report"){
         keyBib = getReportInfo(keyBib);
     } else if (bibType=="unpublished"){
         keyBib = getUnpublishedInfo(keyBib);
     }
     var bibkey = keyBib.key;
     bibtex = keyBib.bib;
     var field;
     if (bibkey != ""){
        // replace the original bibkey with the new one
        bibtex = bibtex.replace(origBibkey, bibkey);
        // also, to save space, remove any abstract written in the bibtex, as such is unnecessary
        var indx1 = bibtex.toLowerCase().indexOf("\,\n abstract \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n abstract \= /i)[0];
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        // the adsnote field can also be removed
        var indx1 = bibtex.toLowerCase().indexOf("\,\n adsnote \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n adsnote \= /i)[0];
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        var indx1 = bibtex.toLowerCase().indexOf("\,\n adsurl \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n adsurl \= /i);
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        // remove a bunch of unneeded fields
        var indx1 = bibtex.toLowerCase().indexOf("\,\n archiveprefix \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n archiveprefix \= /i);
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        indx1 = bibtex.toLowerCase().indexOf("\,\n eprint \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n eprint \= /i);
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        indx1 = bibtex.toLowerCase().indexOf("\,\n primaryclass \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n primaryclass \= /i);
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        indx1 = bibtex.toLowerCase().indexOf("\,\n keywords \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n keywords \= /i);
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        indx1 = bibtex.toLowerCase().indexOf("\,\n month \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n month \= /i);
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        indx1 = bibtex.toLowerCase().indexOf("\,\n number \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n number \= /i);
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
        indx1 = bibtex.toLowerCase().indexOf("\,\n eid \= ");
        if (indx1 != -1){
            field = bibtex.match(/\,\n eid \= /i);
            tmp = bibtex.slice(indx1).replace(field, "");
            tmp = tmp.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
            if (!(tmp.match("CLIPHERE"))){tmp = tmp.replace(/ *\n *\} *$/,"CLIPHERE");}
            tmp = tmp.split("CLIPHERE")[0];
            tmp = field + tmp;
            bibtex = bibtex.replace(tmp,"");
        }
       /*
        // 11/12/2021: put the quotes back into the title: 
        bibtex = bibtex.replace(/ +\,/g,"\,");
        bibtex = bibtex.replace(/\, *\n/g,"\,\n");
        bibtex = bibtex.split("\n");
        for (let i=0; i<bibtex.length; i++){
           var thisBibtex = bibtex[i];
           if (thisBibtex.match(/^title \= /)){
               thisBibtex = thisBibtex.replace(/\= \{ *\"/,'\= \{');
               thisBibtex = thisBibtex.replace(/\" *\}\,$/,'\}\,').replace(/\" *\} *$/,'\}');
               thisBibtex = thisBibtex.replace(/\= \{/,'\= "\{');
               thisBibtex = thisBibtex.replace(/\}\,$/,'\}"\,').replace(/\}$/,'\}"');
               bibtex[i] = thisBibtex;
               break;
           }
        }
        bibtex = bibtex.join("\n");
        */
     } else {
        bibkey = 'error';
     }
  }
  return {"bibtex":bibtex.trim(), "origBibtex":origBibtex, "bibType":bibType, "bibkey":bibkey, "origBibkey":origBibkey};
}
////////////////////////////////////// getBibInfo //////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////// getJournalAbbreviation ////////////////////////////////////////
function getJournalAbbreviation(journal){
   var journalAbbrev = "";
   var pageNotation = "";
   var fields = journalInfo();
   // normalize the journal name so that it comparable to the journal database of names:
   journal = journal.replace(/\&/g, " and ").replace(/\./g, " ").replace(/\W/g, " ").replace(/ +/g," ").trim().replace(/\_/g," ").toLowerCase().trim();
   // construct the regex.  Example:  if full name is "the Astronomical Journal", then the regex that will
   // capture all possibilities without allowing false-positives is the following:
   // ^(?:(?:the\s)|(?:th\s)|t\s)?a\s?(?:(?:stronomical\s)|(?:stronomica\s)|(?:stronomic\s)|(?:stronomi\s)|(?:stronom\s)|
   // (?:strono\s)|(?:stron\s)|(?:stro\s)|(?:str\s)|(?:st\s)|s\s)?j\s?(?:(?:ournal\s)|(?:ourna\s)|(?:ourn\s)|(?:our\s)|
   // (?:ou)|o)?$
   var matchedIndex = -1;
   var matchedChars = -1;
   for (let i=0; i<fields.length; i++){
      fields[i][0] = fields[i][0].replace(/\&/g, " and ").replace(/\./g, " ").replace(/\W/g, " ").replace(/ +/g," ").trim().replace(/\_/g, " ").trim();
      var regex = '';
      // now start going thru each word in the full journal name. If the word has no required letters, then the entire
      // word is optional and should end with a ?. If the word has required letters, allow the word to appear as
      // illustrated in the following example for AstroPhysics:
      //      Astrophysics, Astrophysic, Astrophysi, Astrophys, Astrophy, Astroph, Astrop, Ap
      // Note that we start dropping letters at the end up to the first required letter
      // encoutered, and then the only additional allowed combo would be the required letters only
      var eachWord = fields[i][0].split(" ");
      for (let j = 0; j < eachWord.length; j++) {
          var sp = / /.source;
          if (j == eachWord.length -1) {sp = '';}
          var tmp = '';
          var reqLet = '';
          for (let k = eachWord[j].length; k > 0; k--) {
              if (eachWord[j].charAt(k-1) === eachWord[j].charAt(k-1).toUpperCase()) {reqLet = eachWord[j].charAt(k-1).toLowerCase() + reqLet;}
              if (!reqLet && k > 1) {
                  tmp = tmp + '(?:' + eachWord[j].substr(0,k).toLowerCase() + sp + ')|';
              } else if (!reqLet && k == 1) {
                  tmp = '(?:' + tmp + eachWord[j].charAt(0).toLowerCase() + sp + ')?';
              }
              // once you hit the first required letter from the right side of the word, then you stop building the regex, but continue collecting any
              // remaining required letters in the word:
          }
          if (sp) {sp = sp + '?';}
          if (reqLet.length > 1) {tmp = '(?:' + tmp + '(?:' + reqLet.toLowerCase() + sp + '))';} else if (reqLet) {tmp = '(?:' + tmp + reqLet.toLowerCase() + sp + ')'; }
          regex = regex + tmp;
      }
      // do we have a match? 
      // need to filter out all characters in the journal name that are not represented in this regex, like dashes, etc.
      var filteredJournal = filterTheText(regex, journal);
      if (filteredJournal.match(new RegExp(regex)) && filteredJournal.match(new RegExp(regex)).length > matchedChars){
          matchedIndex = i;
          matchedChars = filteredJournal.match(new RegExp(regex)).length;
      }
   }
   if (matchedChars > 0){
      journalAbbrev = fields[matchedIndex][1]; 
      pageNotation = fields[matchedIndex][2];
   }
   return [journalAbbrev, pageNotation];
}
///////////////////////////////// getJournalAbbreviation ////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////// filterTheText ////////////////////////////////////////////
function filterTheText(reg, text) {
   // This function filters the text using a regex that specifies a list of characters that are allowed. Any characters that are NOT allowed
   // are replaced with "" in the filtered text (which is returned by this function). This filtering is done by starting at the first character
   // in the text and going thru character by character rather than in one fell swoop. Going thru character by character generates a record of
   // all the positions (in the original text) of characters that passed through the filter (e.g., the allowed characters).
   text = text.replace(/^\*/,'');
   var j = 0;
   var tmp = '';
   var filtered = '';
   // make sure that \s and " " mean the same thing:
   var keepTheseChars = reg.replace(/\\s/g," ");
   var whiteSpace = keepTheseChars.match(/ /);
   if (whiteSpace) {whiteSpace = ' ';} else {whiteSpace = '';}
   // normalize the notation within the "regexp" (eg, get rid of unnecessary repetition of backslashes):
   keepTheseChars = new RegExp(keepTheseChars).source;
   // Pull out all the characters that are preceded by a "\"
   keepTheseChars = keepTheseChars.match(/\\[ -~]/g);
   // if there were matches, make a unique list of these characters:
   if (keepTheseChars) {
      keepTheseChars = ([... new Set(keepTheseChars)]).join('');
      keepTheseChars = new RegExp('[' + keepTheseChars + whiteSpace + "a-zA-Z0-9\|]");
   } else {
      keepTheseChars = new RegExp('[' + whiteSpace + "a-zA-Z0-9\|]");
   }
   // Now filter the text so that everything EXCEPT the characters making up the regex are screened out of
   // the text before the regex search is applied:
   for (j = 0; j < text.length; j++) { // go through paper's text, one character at a time
      tmp = text.charAt(j).match(keepTheseChars);
      // record the positions of the characters that survive the filter
      if (tmp) {filtered = filtered + text.charAt(j);}
   }
   return filtered;
}
///////////////////////////////////// filterTheText ////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////// getFirstAuthor ////////////////////////////////////////////
function getFirstAuthor(bibtex){
   var maxAuthor = 10;
   var nAuthor = 0;
   var etal = "";
   var indx1, indx2;
   var firstAuthor = bibtex.match(/authors? \= /i);
   var ands,amps;
   var tmp;
   if (firstAuthor){
       firstAuthor = bibtex.replace(/authors? \= /i, "author \= ");
       indx1 = firstAuthor.indexOf("author \= ");
       firstAuthor = firstAuthor.slice(indx1).replace(/author \= /i,"");
       firstAuthor = firstAuthor.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
       firstAuthor = firstAuthor.split("CLIPHERE")[0];
       // if there is already an et al in the author list, then dont mess with the author list.  Otherwise, truncate if author list exceeds 10 people, 
       // which would be indicated by the presence of more than 9 "and"'s. 
       ands = firstAuthor.match(/( and )/ig);
       amps = firstAuthor.match(/\&/);
       if (ands){nAuthor = ands.length;}
       if (amps){nAuthor = nAuthor + amps.length;}
       if (nAuthor > 0){nAuthor = nAuthor + 1;}
       if (!(firstAuthor.match(/et *al/i)) && nAuthor > maxAuthor){
           // need to trim down the author list to just maxAuthor people
           tmp = firstAuthor.replace(/\"/g,"").replace(/\{/g,"").replace(/\}/g,"").trim().replace(/ *\& */g," and ").replace(/ +and +/ig," and ").split(" and ");
           var truncatedAuthorList = [];
           for (let i=0; i<maxAuthor; i++){truncatedAuthorList.push(tmp[i]);}
           truncatedAuthorList = truncatedAuthorList.map(z => "\{" + z.replace(/ *\,/,"\}\,"));
           truncatedAuthorList = "\{" + truncatedAuthorList.join(" and ") + "\, et al." + "\}";
           // revise the bibtex
           bibtex = bibtex.replace(firstAuthor, truncatedAuthorList);
           etal = "+";
       }
       if (nAuthor > 1 || firstAuthor.match(/et *al/i)){etal = "+";}
       firstAuthor = firstAuthor.replace(/\"/g,"").replace(/\{/g,"").replace(/\}/g,"").trim();
       firstAuthor = firstAuthor.trim().replace(/ *\& */g," and ").replace(/ +and +/ig," and ").split(" and ");
       firstAuthor = firstAuthor[0].trim();
       indx1 = firstAuthor.indexOf(",");
       // if there are no commas in the first author name, then the likely format of the name is first initial last rather than last, first initial. 
       // So try to figure out the last name. 
       if (indx1 == -1){
           // try to figure out the first name and initial(s) and remove them
           firstAuthor = firstAuthor.replace(/  +/g," ").replace(/ \- /g,"-");
           firstAuthor = firstAuthor.split(" ");
           firstAuthor = firstAuthor.slice(1);
           firstAuthor = firstAuthor.map(z => z.trim());
           // remove any initials in the name:
           firstAuthor = firstAuthor.filter(z => !(z.match(/^[A-Z]\.$/)));
           // filter out any jr, sr, I, III, etc
           firstAuthor = firstAuthor.filter(z => !(z.match(/^[^aeiouy]+$/i)));
           firstAuthor = firstAuthor.filter(z => !(z.match(/^i+$/i)));
           // are we left with more than 1 "word"?  if so, and if the words to the left of the last word are big words (not short words like "van" or "der"),
           // then we need to continue removing the words. 
           while (firstAuthor.length > 1 && firstAuthor[0].length > 5){firstAuthor = firstAuthor.slice(1);}
           firstAuthor = firstAuthor.join("").trim().toLowerCase();
       } else {firstAuthor = firstAuthor.slice(0,indx1).trim().toLowerCase();}
       var firstAuthor = removeLatexCode(firstAuthor);
       // remove any non-letter characters from the author name, so that for example "van der weil" turns
       // into "vanderweil", "o'connell" turns into "oconnell", etc.
       firstAuthor = firstAuthor.replace(/[^a-z]/g,"");
   } else {
       firstAuthor = "";
   }
   return firstAuthor + "|" + etal + "|" + bibtex;
}
///////////////////////////////////// getFirstAuthor ////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////// getJournal //////////////////////////////////////////////
function getJournal(bibtex){
   var journal = bibtex.match(/journal *\= *\{?([ -~]+)(?:\n|$)/i);
   var pageNotation = "";
   var journalAbbrev = "";
   if (journal){
       journal = journal[1].replace(/\{ */g,"").replace(/\} *\,?$/g,"").trim();
       // turn the journal into an abbreviation, if not already an abbrevuation
       var tmp = getJournalAbbreviation(journal);
       journalAbbrev = tmp[0];
       pageNotation = tmp[1];
   } else {
       journal = "";
   }
   return journal + "|" + journalAbbrev + "|" + pageNotation;
}
/////////////////////////////////////////////////////////////////////////////////////////////////

//////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////// getYear //////////////////////////////////////////////
function getYear(bibtex){
   var year = bibtex.match(/year \= \{? *([0-9]{4})/i);
   if (year){year = year[1];}
   return year;  
}
//////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////// getPage //////////////////////////////////////////////
function getPage(bibtex){
   var page = bibtex.match(/pages? \= \{? *([a-z0-9]+)/i);
   if (page){page = page[1];}
   return page;
}
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////// getVolume //////////////////////////////////////////////
function getVolume(bibtex){
   var volume = bibtex.match(/volume \= \{? *([a-z0-9]+)/i);
   if (volume){volume = volume[1];}
   return volume;
}
/////////////////////////////////////////////////////////////////////////////////////////////////

function removeLatexCode(text){
  // removes latex code detected in text
  while (text.match(/\{ *\\ *[^\}]+\}/i)){text = text.replace(/\{ *\\ *[a-z ]+\}/i,"")}
  return text;
}

/////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////////// getTitle //////////////////////////////////////////////
function getTitle(bibtex){
   var title = bibtex.match(/title \= /i);
   if (title){
      var indx1 = bibtex.toLowerCase().indexOf("title \= ");
      title = bibtex.slice(indx1).replace(/title \= /i,"");
      title = title.replace(/\,\n [a-z]+ \= /i,"CLIPHERE");
      title = title.split("CLIPHERE")[0].trim();
      while (title.match(/^[\"\{ ]/)){title = title.replace(/^[\"\{ ]/,"").trim();}
      while (title.match(/[\"\} ]$/)){title = title.replace(/[\"\} ]$/,"").trim();}
      title = title.replace(/\n/g," ").replace(/ +/g," ").trim();
      // remove any latex that might be embedded in the title
      var title = removeLatexCode(title);
   }
   return title;
}
///////////////////////////////////////// getTitle //////////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////// getArticleInfo /////////////////////////////////////////
function getArticleInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor != "" && firstAuthor != "missing"){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   // ****************** journal ***********************
   tmp = getJournal(keyBib.bib);
   var isArchive = keyBib.bib.match(/(?:(?:eprint \= )|(?:arxiv))/i);
   var journal = tmp.split("|")[0];
   var journalAbbrev = tmp.split("|")[1];
   var pageNotation = tmp.split("|")[2];
   if (keyBib.key != "" && journalAbbrev != ""){
       keyBib.key = keyBib.key + journalAbbrev;
       // the journal needs to be written in abbreviated "latex" form:
       keyBib.bib = keyBib.bib.replace(journal, "\\" + journalAbbrev);
       isArchive = null;
   } else if (keyBib.key != "" && journal.match(/^\\/)) {
       // the journal is already represented in AAS format but not recognizable by this code. Assume the abbreviation is OK
       keyBib.key = keyBib.key + journal.replace(/^\\/g,"").trim();
       isArchive = null;
   } else if (keyBib.key != "" && journal != ""){
       // the journal name is present but not a "standard" astronomy journal. Make up an abbreviation for the bibkey by
       // grabbing all of the capital letters in the journal name and omitting stop words.
       var journalAbbrev = journalAbbrev.replace(/^a /ig," ").replace(/ a /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^an /ig," ").replace(/ an /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^and /ig," ").replace(/ and /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^as /ig," ").replace(/ as /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^at /ig," ").replace(/ at /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^by /ig," ").replace(/ by /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^for /ig," ").replace(/ for /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^from /ig," ").replace(/ from /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^in /ig," ").replace(/ in /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^of /ig," ").replace(/ of /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^on /ig," ").replace(/ on /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^with /ig," ").replace(/ with /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journal.replace(/^the /ig," ").replace(/ the /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/^to /ig," ").replace(/ to /ig," ").replace(/  +/g," ").trim();
       journalAbbrev = journalAbbrev.replace(/[^A-Z]/g,"").trim(); // extracting only the capital letters
       keyBib.key = keyBib.key + journalAbbrev;
       isArchive = null;
   } else if (keyBib.key != "" && isArchive){
       // the journal was not specified but an eprint was, meaning that the article is probably an arxchive paper
       keyBib.key = keyBib.key + "arxiv";
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n journal \= \{missing\}\n\}");
   }
   // ****************** volume ***********************
   var volume = getVolume(keyBib.bib);
   if (keyBib.key != "" && volume){
       keyBib.key = keyBib.key + volume;
   } else if (!(isArchive)){
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n volume \= \{missing\}\n\}");
   } 
   // ****************** page ***********************
   var page = getPage(keyBib.bib);
   if (page){
       var pg = page.match(/([0-9]+)/);
       if (pg){pg = pg[0];} else {pg = "";}
   }
   if (keyBib.key != "" && pg != ""){
       keyBib.key = keyBib.key + "_" + pg + pageNotation;
   } else if (!(isArchive)){
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n pages \= \{missing\}\n\}");
   }
   // ==========================================
   return keyBib;
}
/////////////////////////////////////// getArticleInfo /////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////////// getBookInfo ///////////////////////////////////////////
function getBookInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'book';}
   return keyBib;
}
///////////////////////////////////////// getBookInfo ///////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////// getBookletInfo /////////////////////////////////////////
function getBookletInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'booklet';}
   return keyBib;
}
//////////////////////////////////////// getBookletInfo /////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////// getInBookInfo /////////////////////////////////////////
function getInBookInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'inbook';}
   // ****************** page ***********************
   var page = getPage(keyBib.bib);
   if (keyBib.key != "" && page){
       keyBib.key = keyBib.key + "_" + page.trim();
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n pages \= \{missing\}\n\}");
   }
   return keyBib;
}
//////////////////////////////////////// getInBookInfo /////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////// getInCollectionInfo //////////////////////////////////////
function getInCollectionInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'incollection';}
   // ****************** page ***********************
   var page = getPage(keyBib.bib);
   if (keyBib.key != "" && page){
       keyBib.key = keyBib.key + "_" + page.trim();
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n pages \= \{missing\}\n\}");
   }
   return keyBib;
}
////////////////////////////////////// getInCollectionInfo //////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////// getInProceedingsInfo //////////////////////////////////////
function getInProceedingsInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'inproceedings';}
   // ****************** page ***********************
   var page = getPage(keyBib.bib);
   if (keyBib.key != "" && page){
       keyBib.key = keyBib.key + "_" + page.trim();
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n pages \= \{missing\}\n\}");
   }
   return keyBib;
}
///////////////////////////////////// getInProceedingsInfo //////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////// getThesisInfo //////////////////////////////////////////
function getThesisInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'thesis';}
   return keyBib;
}
//////////////////////////////////////// getThesisInfo //////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////// getManualInfo //////////////////////////////////////////
function getManualInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'manual';}
   return keyBib;
}
//////////////////////////////////////// getManualInfo //////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////////// getMiscInfo ///////////////////////////////////////////
function getMiscInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'misc';}
   return keyBib;
}
///////////////////////////////////////// getMiscInfo ///////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////// getProceedingsInfo ///////////////////////////////////////
function getProceedingsInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'proceedings';}
   return keyBib;
}
////////////////////////////////////// getProceedingsInfo ///////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////// getReportInfo //////////////////////////////////////////
function getReportInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'report';}
   return keyBib;
}
//////////////////////////////////////// getReportInfo //////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////// getUnpublishedInfo ///////////////////////////////////////
function getUnpublishedInfo(keyBib){      
   // ****************** author ***********************
   var tmp = getFirstAuthor(keyBib.bib);
   var firstAuthor = tmp.split("|")[0];
   var etal = tmp.split("|")[1];
   keyBib.bib = tmp.split("|")[2];
   keyBib.key = "";
   if (firstAuthor){
       keyBib.key = firstAuthor + etal;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n author \= \{missing\}\n\}");
   }
   // ****************** year ***********************
   var year = getYear(keyBib.bib);
   if (keyBib.key != "" && year){
       keyBib.key = keyBib.key + year;
   } else {
       keyBib.key = "";
       keyBib.bib = keyBib.bib.replace(/\n\}$/,"\,\n year \= \{missing\}\n\}");
   }
   if (keyBib.key != ""){keyBib.key = keyBib.key + 'unpublished';}
   return keyBib;
}
////////////////////////////////////// getUnpublishedInfo ///////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////////// searchForTopics /////////////////////////////////////////
function searchForTopics(){
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var windowSize = consts.windowSize;
   var html = HtmlService.createTemplateFromFile('pdfSearch');
   var html = html.evaluate().setSandboxMode(HtmlService.SandboxMode.IFRAME).setWidth(windowSize.width).setHeight(windowSize.height);
   SpreadsheetApp.getUi().showModalDialog(html, 'SEARCH for TOPICS');   
}
/////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////// displayPdf ///////////////////////////////////////////
function displayPdf(){
   deleteCacheChunks("consts");
   deleteCacheChunks("toBeProcessedIds");
   getConstants();
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var windowSize = consts.windowSize;
   var sheetNames = consts.sheetNames;
   var alertText = 'You are on the wrong sheet for pdf-displaying!\n'+
                   'You need to be on the '+sheetNames.bibtex+' tab/sheet and then click on the row of the paper you wish to display!'
   if (SpreadsheetApp.getActiveSheet().getName() != sheetNames.bibtex){SpreadsheetApp.getUi().alert(alertText); return;}
   var ss = SpreadsheetApp.getActiveSpreadsheet();
   var ssId = ss.getId();
   var bibsheet = ss.getSheetByName(sheetNames.bibtex);
   var row1 = bibsheet.getRange('bibUpperLeft').getRow();
   var col1 = bibsheet.getRange('bibUpperLeft').getColumn();
   // grab the pdf's ID for the selected entry, quickly, before a possible collaborator's editing changes where "active range" lands (I
   // don't know if activeRange changes if another person, for example, adds a row above the selected row or not).
   var row = bibsheet.getActiveRange().getRow();
   // if no row has been selected, let the user know:
   var alertText = "You need to select the row of the paper to be displayed by clicking somewhere on that row within the spreadsheet.";
   if (!(row) || row < row1){SpreadsheetApp.getUi().alert(alertText); return;}
   var fileIdCol = bibsheet.getRange("fileId").getColumn();
   var pdfId = bibsheet.getRange(row, fileIdCol).getDisplayValue();
   // now read in all the information associated with this pdf file from both the PDF FILE LIST and the TAG SEARCH tabs: 
   var storedInfo = getInfoForThisPaper(pdfId);
   // make sure that all the needed info is present in order to display the pdf file:  needs to have an error-free URL and an id number
   if (pdfId == '' || pdfId.match(/error/) || storedInfo.url == '' || storedInfo.url.match(/error/)) {
       var alertText = 'You have selected an entry that is missing critical information (either a file ID number and/or a URL link to the pdf file.\n'+
                       'You need to complete this information on the spreadsheet in order to display the paper.'
       SpreadsheetApp.getUi().alert(alertText); return;
   }
   storedInfo['pdfId'] = pdfId;
   storedInfo['folderId'] = consts.folderId;
   storedInfo['windowSize'] = consts.windowSize;
   storedInfo['maxTagLevels'] = consts.maxTagLevels;
   storedInfo['hidePopupAfterThisManySeconds'] = consts.hidePopupAfterThisManySeconds;
   var tagLibrary = getTagLibrary();
   storedInfo['tagLibrary'] = tagLibrary;
   storedInfo['original'] = {'tagLibrary':storedInfo['tagLibrary'], 'pdf':storedInfo['pdf'], 'commentIdList':storedInfo.commentIdList};
   for (let commentId of storedInfo.commentIdList){storedInfo.original[commentId] = storedInfo[commentId];}
   // display a pdf file in a separate frame
   var html = HtmlService.createTemplateFromFile('pdfDisplay');
   html.hiddenStorage = JSON.stringify(storedInfo);
   var html = html.evaluate().setSandboxMode(HtmlService.SandboxMode.IFRAME).setWidth(windowSize.width).setHeight(windowSize.height);
   SpreadsheetApp.getUi().showModalDialog(html, storedInfo.bibkey + '  ' + storedInfo.title);   
}
////////////////////////////////////////// displayPdf ///////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

function getSourceType(pdfId){
   var sourceType = 'google';
   if (!(pdfId.match(/^[a-zA-z0-9\_\-]{33,}$/))){sourceType = "ads";}
   return sourceType;
}

/////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////// getInfoForThisPaper /////////////////////////////////////////
function getInfoForThisPaper(pdfId){
   var sourceType = getSourceType(pdfId);
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var symbols = consts.symbols;
   var sheetNames = consts.sheetNames;
   var ss = SpreadsheetApp.getActiveSpreadsheet();
   // define columns/rows in the PDF FILE LIST sheet:
   var bibsheet = ss.getSheetByName(sheetNames.bibtex);
   var bibrow1 = bibsheet.getRange('bibUpperLeft').getRow();
   var bibcol1 = bibsheet.getRange('bibUpperLeft').getColumn();
   var hasTagCol = bibsheet.getRange('bibcommented').getColumn();
   var hasCommentCol = bibsheet.getRange('bibcommented').getColumn();
   var bibStatusCol = bibsheet.getRange('bibStatus').getColumn();
   var bibkeyCol = bibsheet.getRange('bibkey').getColumn();
   var titleCol = bibsheet.getRange('bibtitle').getColumn();
   var bibtexCol = bibsheet.getRange('bibtex').getColumn();
   var bibPdfIdCol = bibsheet.getRange('fileId').getColumn();
   var urlCol = bibsheet.getRange('bibPdfUrl').getColumn();
   var bibLastCol = bibsheet.getRange('allBibHeaders').getLastColumn();
   // determine the row of this pdf in the bibsheet (I know that we could use activeSelection, but there may be
   // cases where such is not helpful so let's have a more generic solution, which we give below:)
   var rowInBibsheet = bibsheet.getRange('fileId').getDisplayValues().map(z => z[0].trim());
   rowInBibsheet = rowInBibsheet.map(function(z,k){if (z == pdfId){return Number(k)+Number(bibrow1);} else {return -1;}}).filter(z => z != -1)[0];
   // Now extract the entire row to gather information for this pdf within the PDF FILE LIST sheet:
   var bibWholeRow = bibsheet.getRange(rowInBibsheet,1,1,bibLastCol).getDisplayValues()[0];
   var status = bibWholeRow[bibStatusCol-1];
   if (status && status != '' && status == symbols.isOK){status = true;} else {status = false;}
   var bibkey = bibWholeRow[bibkeyCol-1]; if (bibkey){bibkey = bibkey.trim();}
   var title = bibWholeRow[titleCol-1]; if (title){title = title.trim();}
   var bibtex = bibWholeRow[bibtexCol-1]; if (bibtex){bibtex = bibtex.trim();}
   var pdfUrl = bibWholeRow[urlCol-1]; if (pdfUrl){pdfUrl = pdfUrl.trim();}
   var entryInfo = {"status":status, "bibkey":bibkey, "title":title, "bibtex":bibtex, "url":pdfUrl,"sourceType":sourceType,
                    "commentIdList":[], "commentPages":[], "pdf":{"tagNameList":[], "tagIdList":[], "tagEdited":false}};
   // - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - 
   // now define columns/rows in the TAG SEARCH sheet:
   var tagsheet = ss.getSheetByName(sheetNames.search);
   var tagrow1 = tagsheet.getRange('tagUpperLeft').getRow();
   var tagcol1 = tagsheet.getRange('tagUpperLeft').getColumn();
   var tagPdfIdCol = tagsheet.getRange('pId').getColumn();
   var commentIdCol = tagsheet.getRange('pcId').getColumn();
   var quoteCol = tagsheet.getRange('quote').getColumn();
   var usernoteCol = tagsheet.getRange('usernote').getColumn();
   var tagSearchWordCol = tagsheet.getRange('searchtagIds').getColumn();
   var tagFullnameCol = tagsheet.getRange('tagPathname').getColumn();
   var tagIdCol = tagsheet.getRange('searchtagIds').getColumn();
   var coordsCol = tagsheet.getRange('searchCommentCoords').getColumn();
   var pcCol = tagsheet.getRange('paperOrComment').getColumn();
   var tagLastColumn = tagsheet.getRange('allTagSearchHeaders').getLastColumn();
   // get all rows in tagsheet assocuiated with this pdf -- could be the entry for the tags of the pdf as a whole, or entries for comments of this pdf:
   var rowsInTagsheet = tagsheet.getRange('pId').getDisplayValues().map(z => z[0].trim());
   rowsInTagsheet = rowsInTagsheet.map(function(z,k){if (z == pdfId){return Number(k)+Number(tagrow1);} else {return -1;}}).filter(z => z != -1);
   // now go through these rows in the tagsheet and extract the info
   var commentPages = [];
   for (let row of rowsInTagsheet){
       // extract the whole row
       var tagWholeRow = tagsheet.getRange(row,1,1,tagLastColumn).getDisplayValues()[0];
       var tagsheetPdfId = tagWholeRow[tagPdfIdCol-1];
       var commentId = tagWholeRow[commentIdCol-1];
       var quote = tagWholeRow[quoteCol-1];
       var usernote = tagWholeRow[usernoteCol-1];
       var tagFullname = tagWholeRow[tagFullnameCol-1].split("|");
       var tagIds = tagWholeRow[tagIdCol-1].split("|");
       var coordInfos = tagWholeRow[coordsCol-1].split("|");
       var pc = tagWholeRow[pcCol-1];
       var coords = {};
       if (pc == 'C'){
           // this entry is that of a comment
           entryInfo.commentIdList.push(commentId);
           entryInfo[commentId] = {"quote":quote, "usernote":usernote, "tagNameList":tagFullname, "tagIdList":tagIds, "coords":[], "edited":false};
           for (let coordInfo of coordInfos){
               var val = coordInfo.match(/p([0-9]+)x([0-9\.\-\+]+)y([0-9\.\-\+]+)x([0-9\.\-\+]+)y([0-9\.\-\+]+)/);
               var pg = val[1];
               var x1 = val[2];
               var y1 = val[3];
               var x2 = val[4];
               var y2 = val[5];
               entryInfo[commentId].coords.push({"p":pg,"x1":x1,"y1":y1,"x2":x2,"y2":y2});
               commentPages.push(pg);
           }
       } else {
           entryInfo.pdf.tagNameList = tagFullname;
           entryInfo.pdf.tagIdList = tagIds;
       }
   }
   var commentPages = ([... new Set(commentPages)]).sort();
   entryInfo.commentPages = commentPages;
   return entryInfo;
}    
/////////////////////////////////// getInfoForThisPaper /////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////// uploadChanges /////////////////////////////////////////
function uploadChanges(storedInfo){
   // takes the hidden storage info from the html file and looks for any changes, signified by a status of "toBeAddedToPdf", and then incorporates
   // the changes such as new tag, removed tag, new comment, new level 1 and/or level 2 tag, etc into the spreadsheets.
   storedInfo = JSON.parse(storedInfo);
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var sheetNames = consts.sheetNames;
   var symbols = consts.symbols;
   var tagLibrary = storedInfo.tagLibrary;
   // ============================================================================================================
   //                look for changes in tag assignemnt of the pdf file as a whole
   // ============================================================================================================
   var pdfId = storedInfo.pdfId;
   // have any of the tags changed for the pdf as a whole, relative to before the pdf was displayed? 
   if (storedInfo['pdf']['tagEdited']){
       // if the pdf-wide tags have changed, then write the new tags into TAG SEARCH sheet
       var ss = SpreadsheetApp.getActive();
       var tagsheet = ss.getSheetByName(consts.sheetNames.search);
       var row1 = tagsheet.getRange('tagUpperLeft').getRow();
       var col1 = tagsheet.getRange('tagUpperLeft').getColumn();
       var col2 = tagsheet.getRange('tagUpperRight').getColumn();
       var insertAboveThisRow = tagsheet.getRange('insertAboveThisTagRow').getRow();
       var lastOccupiedRow = tagsheet.getRange('pId').getValues().map(function(z,k){if (z[0].trim() != ''){return Number(k)+Number(row1);} else {return -1;}});
       lastOccupiedRow = lastOccupiedRow.filter(z => z != -1);
       if (lastOccupiedRow && lastOccupiedRow !== undefined && lastOccupiedRow !== null && lastOccupiedRow.length > 0){
          lastOccupiedRow = Math.max(... lastOccupiedRow);
       } else {
          lastOccupiedRow = row1 - 1;
       }
       var entry = makePdfSearchEntry(pdfId,storedInfo);
       // determine what row this pdf is on in the spreadsheet
       var thisRow = tagsheet.getRange('pcId').getDisplayValues().map(function(z,k){if (z[0].trim()==pdfId){return Number(k)+Number(row1);} else {return -1;}});
       thisRow = thisRow.filter(z => z != -1);
       if (thisRow && thisRow !== undefined && thisRow !== null && thisRow.length > 0){
           thisRow = thisRow[0];
           if (entry.length == 0){
               // this entry needs to be removed
               tagsheet.deleteRow(thisRow);
           } else {
               tagsheet.getRange(thisRow,col1,1,entry.length).setValues([entry]);
           }
       } else if (entry.length > 0){
           thisRow = lastOccupiedRow + 1;
           // a new row needs to be made, as the paper was never tagged before
           // add a new row, if needed, before before adding the new entry
           if (thisRow >= insertAboveThisRow){
               // get a row for the format
               tagsheet.insertRowsAfter(lastOccupiedRow,10); insertAboveThisRow = insertAboveThisRow + 10;
               var formatRange = tagsheet.getRange(lastOccupiedRow,1,1,col2);
               var newRowRange = tagsheet.getRange(lastOccupiedRow+1,1,10,col2);
               formatRange.copyTo(newRowRange, {formatOnly:true});
           }
           tagsheet.getRange(thisRow,col1,1,entry.length).setValues([entry]);
           lastOccupiedRow = lastOccupiedRow + 1;
       }
       storedInfo['pdf']['tagEdited'] = false;
   }
   // ============================================================================================================
   //                look for edits or new additions to comments
   // ============================================================================================================
   var editedCommentIds = storedInfo.commentIdList.filter(z => storedInfo[z].edited);
   for (let commentId of editedCommentIds){
       if (!(ss) || ss === undefined || ss === null){var ss = SpreadsheetApp.getActive();}
       if (!(tagsheet) || tagsheet === undefined || tagsheet === null){var tagsheet = ss.getSheetByName(consts.sheetNames.search);}
       if (!(row1) || row1 === undefined || row1 === null){
           var row1 = tagsheet.getRange('tagUpperLeft').getRow();
           var col1 = tagsheet.getRange('tagUpperLeft').getColumn();
           var col2 = tagsheet.getRange('tagUpperRight').getColumn();
           var insertAboveThisRow = tagsheet.getRange('insertAboveThisTagRow').getRow();
           var lastOccupiedRow = tagsheet.getRange('pId').getValues().map(function(z,k){if (z[0].trim() != ''){return Number(k)+Number(row1);} else {return -1;}});
           lastOccupiedRow = lastOccupiedRow.filter(z => z != -1);
           if (lastOccupiedRow && lastOccupiedRow !== undefined && lastOccupiedRow !== null && lastOccupiedRow.length > 0){
              lastOccupiedRow = Math.max(... lastOccupiedRow);
           } else {
              lastOccupiedRow = row1 - 1;
           }
       }
       // if the comment's tags or quote/note have changed, then write the new tags and/or quote/notes into TAG SEARCH sheet
       var entry = makeCommentSearchEntry(pdfId, commentId, storedInfo);
       // determine what row this pdf is on in the spreadsheet
       var thisRow = tagsheet.getRange('pcId').getDisplayValues().map(function(z,k){if (z[0].trim()==commentId){return Number(k)+Number(row1);} else {return -1;}});
       thisRow = thisRow.filter(z => z != -1);
       if (thisRow && thisRow !== undefined && thisRow !== null && thisRow.length > 0){
           thisRow = thisRow[0];
           if (entry.length == 0){
               // need to remove this comment
               tagsheet.deleteRow(thisRow);
               delete storedInfo[commentId];
           } else { 
               tagsheet.getRange(thisRow,col1,1,entry.length).setValues([entry]);
           }
       } else if (entry.length > 0){
           thisRow = lastOccupiedRow + 1;
           // a new entry needs to be made, as the paper was never tagged before
           // add a new row, if needed, before before adding the new entry
           if (thisRow >= insertAboveThisRow){
               tagsheet.insertRowsAfter(lastOccupiedRow,10); insertAboveThisRow = insertAboveThisRow + 10;
               var formatRange = tagsheet.getRange(lastOccupiedRow,1,1,col2);
               var newRowRange = tagsheet.getRange(lastOccupiedRow+1,1,10,col2);
               formatRange.copyTo(newRowRange, {formatOnly:true});
           }
           tagsheet.getRange(thisRow,col1,1,entry.length).setValues([entry]);
           lastOccupiedRow = lastOccupiedRow + 1;
       }
       storedInfo[commentId].edited = false;
   }
   // ============================================================================================================
   //                look for edits to the tag dictionary
   // ============================================================================================================
   // have any of the tags in the library changed? 
   var editedLibraryTagIds = storedInfo.tagLibrary.tagIdList.filter(z => storedInfo.tagLibrary[z].edited);
   for (let tagId of editedLibraryTagIds){
       if (!(ss) || ss === undefined || ss === null){var ss = SpreadsheetApp.getActive();}
       var dictsheet = ss.getSheetByName(sheetNames.tagDictionary);
       var row1 = dictsheet.getRange('dictUpperLeft').getRow();
       var col1 = dictsheet.getRange('dictUpperLeft').getColumn();
       var col2 = dictsheet.getRange('dictUpperRight').getColumn();
       var insertAboveThisRow = dictsheet.getRange('insertAboveThisDictionaryRow').getRow();
       var lastOccupiedRow = dictsheet.getRange('tagId').getDisplayValues().map(function(z,k){if (z[0].trim() != ''){return Number(k)+Number(row1);} else {return -1;}});
       lastOccupiedRow = lastOccupiedRow.filter(z => z != -1);
       if (lastOccupiedRow && lastOccupiedRow !== undefined && lastOccupiedRow !== null && lastOccupiedRow.length > 0){
          lastOccupiedRow = Math.max(... lastOccupiedRow);
       } else {
          lastOccupiedRow = row1 - 1;
       }
       var entry = makeTagDictionaryEntry(tagId, storedInfo);
       // determine what row this tag id corresponds to in the spreadsheet
       var thisRow = dictsheet.getRange('tagId').getDisplayValues().map(function(z,k){if (z[0].trim() == tagId){return Number(k)+Number(row1);} else {return -1;}});
       thisRow = thisRow.filter(z => z != -1);
       if (thisRow && thisRow !== undefined && thisRow !== null && thisRow.length > 0){
           thisRow = thisRow[0];
           // write to the file
           dictsheet.getRange(thisRow,col1).setRichTextValue(entry);
           dictsheet.getRange(thisRow,col1+1).setValue(tagId);
       } else {
           // must be a brand new tag, as it's id number is not listed in the sheet
           thisRow = lastOccupiedRow + 1;
           // a new row needs to be made, as the paper was never tagged before
           // add a new row, if needed, before before adding the new entry
           if (thisRow >= insertAboveThisRow){
               dictsheet.insertRowsAfter(lastOccupiedRow,10); insertAboveThisRow = insertAboveThisRow + 10;
               var formatRange = dictsheet.getRange(lastOccupiedRow,1,1,col2);
               var newRowRange = dictsheet.getRange(lastOccupiedRow+1,1,10,col2);
               formatRange.copyTo(newRowRange, {formatOnly:true});
           }
           dictsheet.getRange(thisRow,col1).setRichTextValue(entry);
           dictsheet.getRange(thisRow,col1+1).setValue(tagId);
           lastOccupiedRow = lastOccupiedRow + 1;
       }
       storedInfo.tagLibrary[tagId].edited = false;
   }
   return JSON.stringify(storedInfo);
}   
////////////////////////////////////////  uploadChanges //////////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////
   
/////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////// getPdfBase64Encoded //////////////////////////////////////
function getPdfBase64Encoded(storedInfo){
   if (storedInfo.sourceType == 'ads'){
       var blob = UrlFetchApp.fetch(storedInfo.url).getBlob();
   } else {
       var file = DriveApp.getFileById(storedInfo.pdfId);
       var blob = file.getBlob();
   }
   //https://stackoverflow.com/questions/57418118/how-to-convert-google-apps-script-blob-to-a-base64-encoded-string
   // see also
   // https://stackoverflow.com/questions/42955822/download-a-pdf-generated-by-apps-script-via-web-app
   // and 
   // https://stackoverflow.com/questions/50023812/google-apps-script-how-to-create-pdf-file-from-base64-encoded-data
   var base64encoded = Utilities.base64Encode(blob.getBytes());
   return base64encoded;
}
////////////////////////////////////// getPdfBase64Encoded //////////////////////////////////////
/////////////////////////////////////////////////////////////////////////////////////////////////

//////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////// getWhoAmI //////////////////////////////////////
function getWhoAmI(){
   var question = 'Your ADS token is needed in order to retrieve information from the NASA ADS.\n'+
                  'You should have already entered your token in the "TOKEN" tab.\n'+
                  'Please type in your identity in the text box so that the correct token can be retrieved.'
   var whoAmI = Browser.inputBox(question);
   // store the user in user cache
   var numberOfSeconds = 30*24*60*60; // units of seconds
   putCacheChunks(whoAmI, 'whoAmI',numberOfSeconds);
}
///////////////////////////////////// getWhoAmI //////////////////////////////////////
//////////////////////////////////////////////////////////////////////////////////////

//////////////////////////////////////////////////////////////////////////////////////
/////////////////////////////////// getInfoFromADS ///////////////////////////////////
function getInfoFromADS(adsBibcode){
   //The below is how to fetch a pdf file from the arXiv and how to get its NASA ADS bibtex
   var consts = getCacheChunks("consts");
   if (consts == ''){getConstants(); var consts = getCacheChunks("consts");}
   consts = JSON.parse(consts);
   var bibtexUrl = consts.urls.ads.bibtex.replace(/INSERTADSID/g, adsBibcode);
   var linksUrl = consts.urls.ads.links.replace(/INSERTADSID/g, adsBibcode);
   // get user token for the ADS account
   var whoAmI = getCacheChunks("whoAmI");  
   if (whoAmI == '' || whoAmI == 'cancel' || whoAmI === undefined || whoAmI === null){
       var reply = getWhoAmI();
       var whoAmI = getCacheChunks("whoAmI");
   }
   // now that we know who we are, let's get the token
   var token = consts.tokens[whoAmI];
   try {
       var response = UrlFetchApp.fetch(bibtexUrl,
          {
	    	"method": "get",
	    	"headers": {"Authorization": "Bearer "+token, "Accept": "application/json"},
    		"muteHttpExceptions": false,
           });
   } catch(e){
       return {"bibtex":'fetching error', "pdfUrl":'fetching error'};
   }
   var bibtex = response.getContentText();
   // Now get the pdf links
   try {
       var response = UrlFetchApp.fetch(linksUrl,
          {
	    	"method": "get",
		    "headers": {"Authorization": "Bearer "+token, "Accept": "application/json"},
		    "muteHttpExceptions": false,
           });
   } catch(e){
       return {"bibtex":bibtex, "pdfUrl":'fetching error'};
   }
   var info = JSON.parse(response.getContentText());
   var pdfLinkExists = true;
   if (!(info) || info === undefined || info === null){pdfLinkExists = false;}
   if (pdfLinkExists && (!(info.links) || info.links === undefined || info.links === null)){pdfLinkExists = false;}
   if (pdfLinkExists && (!(info.links.records) || info.links.records === undefined || info.links.records === null)){pdfLinkExists = false;}
   if (!pdfLinkExists){return {"bibtex":bibtex, "pdfUrl":'no publically available(?) pdf error'};}
   //
   var records = info.links.records;
   if (records && records !== undefined && records !== null && records.length > 0){
      var pubPdf = records.filter(z => z.link_type.match(/pub_pdf/i));
      var arxivPdf = records.filter(z => z.url.match(/arxiv/)).filter(z => z.url.match(/pdf/));
      if (pubPdf && pubPdf !== undefined && pubPdf !== null && pubPdf.length > 0){
          var pdfUrl = pubPdf[0].url;
      } else if (arxivPdf && arxivPdf !== undefined && arxivPdf !== null && arxivPdf.length > 0){
          var pdfUrl = arxivPdf[0].url;
      } else {
          var pdfUrl = 'no publically available pdf(?) error';
      }
   }
   return {"bibtex":bibtex, "pdfUrl":pdfUrl};
}
/////////////////////////////////// getInfoFromADS ///////////////////////////////////
//////////////////////////////////////////////////////////////////////////////////////
