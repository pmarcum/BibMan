The below is a link to the BibFile Manager spreadsheet on Google Drive:

https://docs.google.com/spreadsheets/d/1LaW2smzXypG2KOH-v4VXHQTDnyrzyWC3fm_6SfVqOyA/copy

If you hit the "Copy" button that appears when you follow the above link, a copy of the spreadsheet will appear on the "Shared With Me" folder in your Google Drive. That copy, which will include the attached script that makes BibFile Manager work, is yours to use for building your personal reference library. Ideally, you would move the file down into a folder designated for BibFile Manager work.  In that same folder is where BibFile Manager will generate a .bib file with entries corresponding to the successfully-processed entries in the BibFile Manager spreadsheet. 

The script should be ready to start accepting new references in order to build your library, right out of the box.  You may have to "accept permissions" when you try running "LIBRARY FUNCTIONS -> UPDATE LIBRARY" the first time. 

Feel free to contact me if you run into permission problems or if you notice any bugs as you use the code. 

A video that describes BibFile Manager and walks through all of its functions, including how to link the .bib file on Google Drive with your Overleaf project, is provided at this YouTube link: https://youtu.be/0x-stS2OXwc

An update to BibFile Manager that describes a new search tool is described in this YouTube link: https://youtu.be/PGiTd0DZIvo

         %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
         %%%%%%%%%%  Thank you for your interest in BibFile Manager!  %%%%%%%%%
         %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

================================
         Updates: 
================================
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
