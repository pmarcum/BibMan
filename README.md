<p style="position: relative; overflow:auto">
  <img src="https://github.com/pmarcum/BibMan/blob/main/BibManLogoHeader.png"
       width=500
       style="display:inline-block;padding-right:10px"
       alt="BibMan-Logo">
      <font size="10"><b>Bib</b></font><font size="5">file</font> <font size="10"><b>Man</b></font><font size="5">ager</font>
</p>

The below is a link to the BibMan (BibFile Manager) spreadsheet on Google Drive:
https://docs.google.com/spreadsheets/d/14OdB0G3kgNXt2zQWM3qWlDrSDLQWgn7pkUQ8V4cuL2E/copy

If you hit the "Copy" button that appears when you follow the above link, a copy of the spreadsheet will appear on the "Shared With Me" folder in your Google Drive. That copy, which will include the attached script that makes BibMan work, is yours to use for building your personal reference library. Ideally, you would move the file down into a folder designated for BibMan activities.  In that same folder is where BibMan will generate a .bib file with entries corresponding to the successfully-processed entries in the BibMan spreadsheet. 

~~The script should be ready to start accepting new references in order to build your library, right out of the box.  You may have to "accept permissions" when you try running "LIBRARY FUNCTIONS -> UPDATE LIBRARY" the first time. More specifically, to get through the authorizations (a one-time only task):~~

BibMan functions are now implemented through buttons that clearly indicate their functionality, instead of the drop-down menu, which are:  (1) updating the library, (2) displaying the Pdf file, and (3) searching for tagged items within the library. 

"Authorization Required" --> click on the GREEN "Continue" 
"Choose an account" --> select the Google Account / email that you wish to use by clicking on it.
"Google hasn't verified this app":  
    --> scroll to the bottom and click on the small grey underlined "Advanced" in lower left corner.
    --> scroll down to bottom and click on small grey underlined "Go to createVotingSystem (unsafe)" at the very bottom.
"Bibfile Manager wants to access your Google Account" --> scroll to the bottom and click the "Allow" button.
After the above steps, you will be able to run the scripts.


Feel free to contact me if you run into permission problems or if you notice any bugs as you use the code. 

A video that describes BibMan and walks through all of its functions, including how to link the .bib file on Google Drive with your Overleaf project, is provided at this YouTube link: https://youtu.be/0x-stS2OXwc (made before version 09102023, the update introducing buttons in the top menu)

An update to BibMan that describes a new search tool is described in this YouTube link: https://youtu.be/PGiTd0DZIvo  (made before version 09102023, the update to buttons in the top menu)

         %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
         %%%%%%%%%%  Thank you for your interest in BibFile Manager!  %%%%%%%%%
         %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

================================
         Updates: 
================================
Latest version is 10192023

10/19/2023: 
- I found a bug that was causing a mis-translation between the page that was being displayed and the thumbnail that was highlighted in blue that was supposed to be the same page.  This effect was noticed only on very large (100-page) documents, so I suspect there was some kind of rounding error that only became noticable when the page size was appreciable.  That part of the code was completely re-written so that no computation is now done to determine what page is being displayed (which previously was computed by taking the total scrollbar length and then dividing by the number of pages in the document, and then determining the fraction that the scrollbar had moved down).  Rather, now the visible page is determined more directly, by performing a .getBoundingClientRect() on every div holding a page canvas, and then finding all the divs that have some portion of their length (between .getBoundingClientRect().top and .getBoundingClientRect().bottom) that lay between the top and bottom of the visible port.  This strategy works beautifully (but perhaps at the expense of a bit more computing time).  Clicking on the thumbnail to go to that corresponding page now works flawlessly, as well, by ditching the computation of where the page should go based on the scroll bar and instead looking up the div's .getBoundingClientRect().top and forcing that value to corresspond to the top of the viewport (previously, sometimes the page would appear scooted down from the top ... again indicating a round-off error in the translation between scroll-length and page number).
- As part of the rework of the page-determination code, the way that the thumbnail strip indicates the page that the viewer is on, has been altered.  Now, the thumbnail strip will indicate if more than 1 page is in the viewport, by highlighting more than one thumbnail image, as appropriate.  Pages that are not at least 1/4th of their pagelength within the visible port are not considered to be visible.
- There is an infrequent, unpredictable bug that I've noticed emerging a few times that I spent time trying to track down:  ocassionally when creating a new comment, after closing the comment and hovering over the fuzzy ball icon to see the comment, one can bring up the comment box and hover over it to keep it open, but as soon as one leaves the box, it closes, even when the "edit" button has been pressed.  Upon further investigation, I noticed that such comments end up without a unique comment ID number.  I don't know how this situation arises (and I spent about a day trying to figure it out).  The only way to deal with it was to remove that comment manually by deleting the row on the "TAG SEARCH" page. I have a suspicion that this situation arises when the user forgets to exit out of the comment and then highlights more text, elsewhere. Following up on this suspicion is on the to-do list. 

10/13/2023:
- Finally, a feature I've been wanting to implement since the get-go:  BibMan now allows continuous scrolling when displaying a PDF file! (You no longer have to click on the page-counter to navigate from one page to the next.) This change required a significant internal restructuring in some areas of the code, particularly those related to annotation/tagging/commenting/highlighting.
- As part of this major shift towards scrolling through the PDF file, a new thumbnail strip along the left side of the display now appears, giving a preview of all pages in the document.  In this new version, to jump to a page (if you don't want to scroll to it), the user clicks on the thumbnail corresponding to the desired page.  The textbox that used to come up, telling what pages that comments are located on, has been removed. In its place, the thumbnails show the comments.  Also, the page numbers along the thumbnails turn violet if one or more comments are on them.  As the user adds comments to a file, the corresponding page numbers turn aqua (the same color as the highlight of new comments), to indicate a new comment now exists on that page(s). 
- A "Help" button has been added, providing a modular, easy-to-navigate user guide.
- The buttons along the top slight changed in appearance.
- Some additional tweaks were done to the code to keep pieces of the drop-down tagging menus from lingering when their parent menus have already timed-out. (Still needs a bit more work, though, as ocassionally I still see this "orphan menu" effect). 

09/19/2023:
- Despite the previous modifications, I encountered some pdf files that got cut off at the bottom (by just a little bit) when displayed. This latest version now preserves all of the pdf pages and applies scaling that does not allow any part of the pages to get cut off. 

09/11/2023: 
- Renamed "Bibfile Manager" to be "BibMan" instead, and created a BibMan logo that appears on the spreadsheet as well as this repository. (The logo was put into version 09102023 without updating the version number). 

09/10/2023:
- I changed the way that the drop-down tag menus are presented.  In the previous version, the menus were "twitchy", disappearing if your mouse accidentally veered off the edge of a tag menu.  Now, if you momentarily fall off the edge of a menu, the menu will not instantly disappear.  Also, the dropdown menus are spaced out a bit more in the horizontal direction to make selection a bit easier.   This seemingly small change necessitated a lot of internal code re-writing. While I was in there, I also did some code clean-up (removing functions no longer called, etc.)  The menus will now fold out to the right or to the left depending on whether the top-level button is on the right or left side of the screen, to insure that the menus do not end up getting cropped out by the edges of the screen.
- Buttons now activate the functions for displaying the pdf, searching on tags, and updating the library.  The drop-down menu that used to be at the top is now gone and superceded by these buttons.
- Policy changed:  In this latest version, when you create a new tag or tag category, that tag will automatically be checked under the assumption that you intend the displayed paper (or comment) to have that tag.  This policy change streamlines the process of tagging, as you now don't have to work your way back through the tag menu to find the new tag you just made so that you can check the box. 

08/29/2023 (PM): 
- Noticed that some pdf files are getting just the very top of the page clipped, so made some additional tweaks to prevent the cropping.
- Aesthetics change:  gave the top tag menu a light gray background to distinguish it from the canvas where the pdf file appears. 

08/29/2023 (AM): 
- Fixed an irritating feature in which the pdf file would occassionally get cropped at the top.  The pdf files now display completely without having to mess around with the zoom.

08/28/2023: 
- Fixed a bug that seemed to be intermittent in the last posted version, in which the pdf files often would not get displayed when "LIBRARY FUNCTIONS -> DISPLAY THE PDF selected in spreadsheet" was executed. There is still a problem when the PDF URL is actually a redirect to another URL (most noticeble issues are with links to MNRAS articles, such as https://academic.oup.com/mnras/pdf-lookup/doi/10.1093/mnras/stw292).  A future version will fix this problem by linking to the ArXiv paper instead.
- Links to JQuery and the PDF.js libraries now point to the most updated versions of those packages.
- Some future nice-to-haves that I thought of while fixing the bug:
-     Continuous scrolling rather than having to use the forward/backward buttons to load each page individually
-     Display all page numbers along the bottom as clickable buttons to take you to that page, and have the page numbers be a different color if comments reside on them.
-     All comments displayed vertically along the right, and if clicked on, transport you to the relevant page. 
  
05/20/2022:
- The script will now put extra rows into the spreadsheet for future entries, every time the script is processed for new additions,  so that the user does not have to constantly add thos new rows theirselves. 
- The script now automatically groups together all the rows except the last couple of rows at the bottom, and folds them up, so that the user does not have to deal with this big long list of entries.  Just click on the toggle "+" or "-" to expand or collapse the group. 
- Fixed a bug: if the same value in the "ADS or Google" column was typed more than once as new entries, the code crashed because of an inherent assumption that new entries would never be duplicative.  This assumption has now been removed, to allow for that human error. 
- Removed the hyperlinks to the pdf files in the "bibkey" column.  Seemed silly to hyper-link those bibkeys since the URL is clearly displayed in the rightmost column, and was just inconvenient to have the hyperlink there when a quick copy/paste of the bibkey was intended for some purpose. 
- The row format was not being applied uniformly to each new entry -- now fixed.
- The row height is now forced to be just enough to allow 2 wrapped rows of the title to show, rather than expanding to fully show the bibtex entry.  The smaller row height allows one to more quickly scroll up/down the list. Seeing the titles and bibkeys are what are most important, but the bibtex can still be viewed by manually widening the row if desired. (If a row height is manually adjusted, it will remain that way, as the fixed row height is only imposed on rows that are processed.) 

05/19/2022:
- Major change: the bibfile.bib can now be more easily linked to Overleaf, using GitHub as a go-between.  I will make a new video to show how the new linkage to Overleaf works.  The improvement is significant, as now one only has to push a single button to upload any new changes made to both the bibfile.bib and to any of the latex tables generated by Proposal Work Effort Tool (helpful if you are working on a proposal instead of a paper). 
- Fixed a bug:  when displaying a pdf and tagging the paper, the tags for the paper would get lost as soon as a comment was created. The paper's tags are now retained AND automatically applied to any comments made in the paper (but those automated tags can be  turned off for comments, as needed). 

02/21/2022:
- Following some heavy usage of this script after some proposal-writing, and going in and making some small tweaks, I decided to make a new version.  I have no idea what changes (if any) there are from the Dec 12 update!  Might have been some trivial changes like conditional formatting changes. But just to be safe, the above now links to the latest version of this script. 

12/10/2021:
- Given all the changes being made over time, I need to start referencing using version numbers.  So let's declare the version that exists on 12/10/2021 to be version 121021 ! (The version number will now be part of the Google File name, e.g., "BIBFILE MANAGER 121021")
- Changed the way that the "PDF URL" column in the "PDF FILE LIST" tab gets colored red as a flag indicating a problem.  Before, the cell would turn red as soon as any text was entered in the "ADS or Google" column, which was annoying when just trying to enter the ADS number to add a new reference to the library.  Now, that column turns red ONLY if there is no URL and if the paper has already been processed by the script (as indicated by some kind of icon in the skinny column just to the left of the "BIBKEY" column on the "PDF FILE LIST" tab. 
- Changed the way the script handles papers that ONLY have an arXiv reference.  Before, the user had to be sure that the bibtex was "@MISC" instead of "@ARTICLE" or some other category, and even then, the rendered citation in the "reference" section of a document looked ugly because the arXiv entries tended to have a lot of redundancy - the word 'arXiv' sometimes appeared 2 times in the citation, along with the spelled-out url pointint to the arXiv article.  Some of this behavior is undoubtedly related to the LaTex class file used, but even so, the script has been modified to better handle cases for which only an arXiv reference is available).  The script now does the following:  if only an arXiv citation is available for a paper, the script removes all the other "clutter" in the bibtex, changes "@[whatever]" to "@MISC" and adds a "howpublished = " field, where the field value is "arXiv:######.#####'.  For example, "howpublished = {arXiv:4444.56565}". The script also looks for the older way to reference arXiv papers, "astro-ph/#######" and will use that phrase in the "howpublished" field if no arXiv number is available (e.g., "howpublished = {astro-ph/589098595808}").  The result, at least when using the AAS class file in the Latex document, is a succinct entry for the arXiv reference in the reference section that provides the arXiv number (or astro-ph number), but suppresses all the redundant references to the arXiv as well as suppresses the arXiv url. 
- Added a warning box for when in the "display pdf" mode, when the user clicks "exit" after having made some changes to the paper (e.g., new comment, tag, etc.). 

11/13/2021: 
- Corrected a bug related to detection of duplicated reference paper entries.  While Google Drive file IDs are unique, even if the files contain duplicated information, the NASA ADS bibcode could hypothetically be written multiple times into the PDF FILE LIST spreadsheet.  The original code would not be able to distinguish one entry from the other, as the "file id" (the NASA ADS bibcode) would be exactly the same for the multiple entries.  The code is now able to recognize when duplicated entries of the same NASA ADS bibcode is listed, and to mark the first one as a legitimate entry and the remaining entries as duplicates. 

11/11/2021: 
- Corrected a bug in which all file ids, regardless of whether they were NASA ADS bibcodes or Google file IDs, got labelled as NASA ADS bibcodes only. (Turns out that not all NASA ADS bibcodes have three periods (...))
- Decided to change a "policy":  originally, if a bibtex could be found for a new reference entry but the pdf link was not obtainable, the code would not provide the bibtex in the spreadsheet/database ... the code insisted on having a complete set of information before listing the bibtex for a reference.  The code will now give the bibtex retrieved from NASA ADS even if a publically-available pdf link is unavailable or not retrievable through the NASA ADS API.  The code will indicate a green checked-box status for that file, allowing its inclusion in the ASCII bibfile.bib.  However, without a pdf URL, the file cannot be displayed or annotated using BibFile Manager.  A check for the existance of a pdf URL and an error box if one is not present, has also been added to the code. 
- The "pdfDisplayTemplate.html" file has been renamed to a more managable "pdfDisplay.html". 
- Decided to change another "policy":  originally, when a new comment was being made, the tag topic edit menu would be initialized with no checked boxes, to allow the user to select the appropriate topic tags for that comment.  Now, the tag topic edit menu is "pre-loaded" with whatever tags that the paper as a whole has at the time that the comment is being made.  Any tag boxes that are pre-checked can easily be un-checked if the tags are not appropriate to the comment. This change might make it easier to tag comments, if there is indeed a lot of overlap in desired tag comments with those for the paper as a whole. 
- The conditional formatting for the pdf Url column in the PDF FILE LIST tab has changed. Originally, cells in this column would turn red as soon as something would be typed into the ADS or Google column.  Now, the cells turn red ONLY if the cell has text with the word "error" in it AFTER being processed (eg, after the "Update Library" menu option has been run) AND the status indicator shows a checked green box.  The intent now is to flag any entry that has a valid bibtex and looks OK except not having a valid PDF URL (and therefore cannot be displayed in the BibFile Manager pdf-viewer, tagged, or annotated).
- If you already have an existing BibFile Manager spreadsheet that has been populated with your reference library and you do not want to download a fresh BibFile Manager spreadsheet that has all of these changes, then here's how to implement all the changes in your existing spreadsheet to preserve your library: 
(1) Click on "Extensions" (located along the top of the spreadsheet, where other menu options such as "File", "Edit", "view", etc are seen), then click on "Apps Script".
(2) In the new tab that appears, click on "Code.gs", select everything, then delete all the content.  Go to the Code.gs file provided in this GitHub folder, copy/paste the contents into your Code.gs file.  After pasting the contents, hit "File"=>"Save".
(3) On the left side menu panel of the code editor, click on the down-triangle associated with the "pdfDisplayTemplate.html" file. Click on "Rename", then type in "pdfDisplay". 
(4) Repeat Step #2, but with "pdfDisplay.html", and copy/pasting the contents of the pdfDisplay.html provided in this GitHub folder. DO NOT FORGET: "File" => "Save".
(5) Go to "File"=>"New"=>HTML.  Type "pdfSearch" into the text box when a file name is requested. Delete the default contents of the new file and paste-in the contents of "pdfSearch.html" provided in this GitHub. DO NOT FORGET: "File" => "Save". (Note: I don't think that anything changed in this file relative to yesterday's update, but can do the copy/paste just to make sure!)
(6) Close out the editor tab on your browser (you did hit File=>Save for each of the modified files, right?!)
(7) In the BibFile Manager spreadsheet, click on the PDF FILE LIST tab (at the very bottom, just click on that word/tab if not already selected). Now right-click the mouse while your cursor is on a cell in the "J" column (the "PDF URL" column).  Select "View More Cell Actions" at the bottom of the pop-up menu, then select "Conditional Formatting"
(8) Click on the "Custom formula" item that pops up in the right side for the J3:J#### range (the #### is just whatever number there might be there, depends on how big your reference library is!). 
(9) In the box below "Custom formula is", replace the formula that is already there with the following (you can just copy the below with your mouse and then paste over the formula in your spreadsheet):

                  =((ISBLANK(INDIRECT("J"&ROW(),TRUE)))+(REGEXMATCH(INDIRECT("J"&ROW(),TRUE),"error")))*(INDIRECT("E"&ROW(),TRUE)="☑")

(10) Click on the green "Done" button at the bottom of the Conditional format rules box. 
(11) Click on the "X" in the upper right of the Conditional format rules menu/box to close it out. 

After completing the above steps, your "old" spreadsheet should now be using the latest/greatest version of the code! 

11/10/2021:
- The following error was corrected: When adding a new reference to the library, if there was no publicly-available pdf file, the code crashed when making the API call to the NASA ADS. The code now gracefully returns an error and marks the line in the spreadsheet as incomplete. 
- A brand new search tool has been implemented! 
A new option is now available in the top-level menu of the spreadsheet that opens up the search tool. Learn all about it here: https://youtu.be/PGiTd0DZIvo.  If you already have downloaded BibFile Manager and already have a reference library started in it, you can do the following to preserve your library:
(1) Click on "Extensions" (located along the top of the spreadsheet, where other menu options such as "File", "Edit", "view", etc are seen), then click on "Apps Script".
(2) In the new tab that appears, click on "Code.gs", select everything, then delete all the content.  Go to the Code.gs file provided in this GitHub folder, copy/paste the contents into your Code.gs file.  After pasting the contents, hit "File"=>"Save".
(3) Repeat Step #2, but with "pdfDisplayTemplate.html", and copy/pasting the contents of the pdfDisplayTemplate.html provided in this GitHub folder. DO NOT FORGET: "File" => "Save".
(4) Go to "File"=>"New"=>HTML.  Type "pdfSearch" into the text box when a file name is requested. Delete the default contents of the new file and paste-in the contents of "pdfSearch.html" provided in this GitHub. DO NOT FORGET: "File" => "Save".
(5) Close out the editor tab on your browser (you did hit File=>Save for each of the modified files, right?!)
After completing the above steps, your "old" spreadsheet should now be using the latest/greatest version of the code! 

10/28/2021:
- An error was found with the selection functionality.  As one clicked on a cell in the "PDF FILE LIST" sheet, the script highlighted the entire row so that the user could more easily see where their cursor was pointing.  This functionality had the undesirable consequence of making it impossible to type new entries into the ADS/Google ID column to add papers to the reference library, so this row-highlighting feature has been removed for the time being. 
