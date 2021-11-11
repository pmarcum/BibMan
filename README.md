The below is a link to the BibFile Manager spreadsheet on Google Drive:

https://docs.google.com/spreadsheets/d/1LaW2smzXypG2KOH-v4VXHQTDnyrzyWC3fm_6SfVqOyA/copy

If you hit the "Copy" button that appears when you follow the above link, a copy of the spreadsheet will appear on the "Shared With Me" folder in your Google Drive. That copy, which will include the attached script that makes BibFile Manager work, is yours to use for building your personal reference library. Ideally, you would move the file down into a folder designated for BibFile Manager work.  In that same folder is where BibFile Manager will generate a .bib file with entries corresponding to the successfully-processed entries in the BibFile Manager spreadsheet. 

The script should be ready to start accepting new references in order to build your library, right out of the box.  You may have to "accept permissions" when you try running "LIBRARY FUNCTIONS -> UPDATE LIBRARY" the first time. 

Feel free to contact me if you run into permission problems or if you notice any bugs as you use the code. 

A video that describes BibFile Manager and walks through all of its functions, including how to link the .bib file on Google Drive with your Overleaf project, is provided at this YouTube link: https://youtu.be/0x-stS2OXwc

         %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
         %%%%%%%%%%  Thank you for your interest in BibFile Manager!  %%%%%%%%%
         %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

================================
         Updates: 
================================
11/10/2021:
- The following error was corrected: When adding a new reference to the library, if there was no publicly-available pdf file, the code crashed when making the API call to the NASA ADS. The code now gracefully returns an error and marks the line in the spreadsheet as incomplete. 
- A brand new search tool has been implemented! A new option is now available in the top-level menu of the spreadsheet that opens up the search tool. Learn all about it here: https://youtu.be/PGiTd0DZIvo

10/28/2021:
- An error was found with the selection functionality.  As one clicked on a cell in the "PDF FILE LIST" sheet, the script highlighted the entire row so that the user could more easily see where their cursor was pointing.  This functionality had the undesirable consequence of making it impossible to type new entries into the ADS/Google ID column to add papers to the reference library, so this row-highlighting feature has been removed for the time being. 
