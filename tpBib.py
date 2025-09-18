# What is this? a python alternative to tools like Zotero or Mendeley. why? because those suck. 
# design criteria: software must be able to:
# watch a folder (and subfolders), and update as new files are added
# automatically detect duplicates (including searching other subfolders)
# allow the user to enter keywords for each file
# allow user to search files
# generate bibtex for files

#viewerCommand="evince" 	# default on xubuntu 
viewerCommand="open" 		# macOS --> launches your default viewer
consecutiveWordThreshold=40	# used for text-based dupe-checking. 40 is a good number. you want to avoid things like re-used (or common) acknowledgements, but still capture like-paragraphs
parallelWorkers=7			# used for parallel dupe-checking. how many cpus do you have? using them all might bog things down if you're trying to leave this running in the background


import glob,os,json,shutil,time,sys
from tqdm import tqdm
from pypdf import PdfReader
from PIL import Image
from pdf2image import convert_from_path
import numpy as np

# Initialize "index" global. what will it contain? When we check all folders/subfolders/files/etc, we'll record the filename, timestamp, and text. this will be saved as tpBib.json. 
index={}
if os.path.exists("tpBib.json"):					# load the old index
	print("loading previous index file")
	with open("tpBib.json") as f:
		index=json.load(f)

# If I somehow corrupted the json file, I can make one-time programmatic corrections here. You shouldn't. 
#for f in index.keys():
#	if "checkedPixelsAgainst" not in index[f].keys():
#		index[f]["checkedPixelsAgainst"]=[]
#	#if f in index[f]["matches"]:
#	#	i=index[f]["matches"].index(f)
#	#	del index[f]["matches"][i]
#	if "ouloukia" in f:
#		for f2 in index[f]["matches"]:
#			if "ouloukia" in f2:
#				unlinkEntries([f,f2])
#	if "checkedTextAgainst" not in index[f].keys():
#		index[f]["checkedTextAgainst"]=[]
#	if "duplicates" in index[f].keys():
#		del index[f]["duplicates"]
#	if "duplicates" not in index[f].keys():
#		index[f]["duplicates"]=[]
#	if "matches" not in index[f].keys():
#		index[f]["matches"]=[]
	#index[f]["text"]=" ".join(index[f]["text"].split())

# read text from pdf file "f", with quality-of-life edits like new-line-fildering etc
def getPdfText(f):
	#try:
	reader = PdfReader(f)
	text = [ page.extract_text() for page in reader.pages ]
	text = " ".join(text)
	text = text.replace("\n"," ")
	words = text.split()
	words = [ w for w in words if len(w)>1 ]
	return words

# return an image of the middle page from pdf file "f". used for image-based dupe-checking
def getMiddlePage(f):
	doc=PdfReader(f)
	nPages=len(doc.pages)
	middle=nPages//2+1
	im=convert_from_path(f,first_page=middle,last_page=middle) # specifying page prevents RAM overload
	return im[0]

# global dict "index" is saved to a json file. we try/except/recurse this function to prevent interruption and corruption of your index file
def saveJson():
	try:
		print("saving json")
		with open("tpBib.json", 'w') as f:					# save off new index dict
			json.dump(index, f, indent=4)
	except:
		print("WARNING: PLEASE DO NOT INTERRUPT JSON SAVE, OR ELSE YOUR DATABASE WILL BE CORRUPTED")
		saveJson()

# given a dict, returns a deep-copy (not just a reference)
def copyof(dic):
	new={}
	for k in dic.keys():
		val=dic[k]
		if isinstance(val,list):
			val=[ v for v in dic[k] ]
		new[k]=val
	return new

# Suppose a file moves. the filename is the key in the index, so we need to make a new entry in the index (with the new filename/location) with all the old contents for that index. We ALSO need to look through all other index entries which might point to the old file! 
def rekey(oldkey,newkey):
	global index
	index[newkey]=copyof(index[oldkey])
	del index[oldkey]
	#print(index[newkey])
	for k in index.keys():
		# for an index entry (pdf file), a dict stores pointers to other files. these are the locations of those pointers. so when we change a file's name or location, we need to check all other files' pointers and update them with this file's new name or location. 
		for pointerKey in ["matches","checkedTextAgainst","checkedPixelsAgainst"]: 
			if oldkey in index[k][pointerKey]:
				i=index[k][pointerKey].index(oldkey)
				del index[k][pointerKey][i]
				index[k][pointerKey].append(newkey)
				#print(k)

# Did you copy your pdfs folder to a new computer, and all the timestamps are hosed? this function will (naively) update the timestamps
def fixTimestamps():
	c=input("WARNING! This will raw update timestamps in the index file based on current filenames. You should * ONLY * use this if you copied your library to a new system and suspect your file's timestamps were changed, * AND *, if you are sure no filenames have been changes, no files have been deleted, or added, since this code was last run on the old system!!! If you understand the risks, please type \"YES\" to continue: ")
	if c!="YES":
		print("timestamps not updated. quitting")
		return
	files=glob.glob("**/*.pdf",recursive=True)				# collect up all files
	global index
	print("updating index")
	for n,f in enumerate(sorted(files)):					# loop through files in folder
		# was file already indexed?
		timestamp=os.path.getmtime(f)						# get file modification time https://stackoverflow.com/questions/237079/how-do-i-get-file-creation-and-modification-date-times
		if f not in index.keys():
			continue
		index[f]["timestamp"]=timestamp
	print("all timestamps updated")

# scan all folders/subfolders, check each file. if it's in the index, check the timestamp, ignore or update. if it's not, add it. check all index entries to see if there are extras. 
def indexing():
	files=glob.glob("**/*.pdf",recursive=True)				# collect up all files
	global index
	print("updating index")
	# ensure all files are in index
	for n,f in enumerate(sorted(files)):					# loop through files in folder
		# was file already indexed?
		timestamp=os.path.getmtime(f)					# get file modification time https://stackoverflow.com/questions/237079/how-do-i-get-file-creation-and-modification-date-times
		if f in index.keys() and index[f]["timestamp"]==timestamp:	# if file is unchanged, ignore
			continue
		# was the file indexed previously, but moved?
		fname=f.split("/")[-1] ; wasMoved=False
		for k in list(index.keys()):
			if fname in k and timestamp==index[k]["timestamp"]:
				print("looks like",k,"was moved to",f)
				wasMoved=True
				rekey(k,f)
				#index[f]=copyof(index[k])
				#del index[k]
				break
		if wasMoved:
			continue
		# or is it a new file! 
		print("adding",f,"to index:\t\t",n,"/",len(files))
		text=" ".join(" ".join(getPdfText(f)).split())			# pull text from pdf (so we can search and deduplicate later)
		entry={ "text":text, "timestamp":timestamp, "checkedTextAgainst":[], "checkedPixelsAgainst":[], "matches":[] }
		index[f]=entry
	# ensure all index entries exist as files! 
	for f in list(index.keys()):							# look through files in index
		if f not in files:						# clear index entries for files which are no longer present
			del index[f]
			print("removing missing file",f,"from index")


# for string-based dupe-checking, prevent certain frequently-occurring long strings from matching
ignoredCharsets=[";"]+[ " "+l+". " for l in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" ]+["Creative Commons Attribution","Reprints and permission information","Nature Research Reporting Summary","Creative Commons license","CreativeCommons license","Reprints and permission information is available at","distribution and reproduction in any medium or format","To view copy of this license"]
# how does string-based dupe-checking work? "chunk" one set of text into N-word-length chunks (sliding window), check if that series of words is in the other. (you could also do longest-common-substring, but we don't need to be that general. all we care about is chunks of words above the threshold in both papers)
def checkForDuplicateTextSingle(threshold=consecutiveWordThreshold):
	global index
	for f1 in list(sorted(index.keys())):
		print(f1)
		for f2 in tqdm(list(index.keys())):
			# don't check self, or recheck ones we've already checked
			if f1==f2:
				continue
			if f2 in index[f1]["checkedTextAgainst"]:
				continue

			# if file 2 has fewer words, it's more efficient to scan through it instead! 
			text1=index[f1]["text"] ; words1=text1.split() ; len1=len(words1)
			text2=index[f2]["text"] ; words2=text2.split() ; len2=len(words2)
			if len2<len1:
				text1,text2=text2,text1
				words1,words2=words2,words1
				len1,len2=len2,len1
			# scan through chunks of words until we reach the end, or until we find something
			for i in range(len1-threshold):
				sub=" ".join(words1[i:i+threshold])

				#e.g. "if ';' in sub". certain characters may indicate, for example, shared citations! 
				if True in [ c in sub for c in ignoredCharsets ]:
					continue
				if sub in text2:
					print("likely match:",f1,f2)
					print(sub)
					index[f1]["matches"].append(f2)
					index[f2]["matches"].append(f1)
					break

			# whether or not we found anything, denote that these two files have been compared
			index[f1]["checkedTextAgainst"].append(f2)
			index[f2]["checkedTextAgainst"].append(f1)

# parallelized: works the same as checkForDuplicatesSingle, but using a multiprocessing pool
def checkForDuplicateTextParallel(threshold=consecutiveWordThreshold):
	global index

	from multiprocessing import Pool, Process, Manager, set_start_method #, Array, Value
	set_start_method('fork')
	manager = Manager()
	dic = manager.dict()							# shared dict for multiprocessing pool to record results to. 

	args=[]						# list containing arguments to pass to the workers. dict, file1, file2, word threshold
	print("calculate args")
	files=list(sorted(index.keys()))
	for i,f1 in enumerate(tqdm(files[:-1])):	# ignore the last file (all previous filess, vs the last, the last should be covered)
		for j,f2 in enumerate(files[i+1:]):	# ignore all previous files (where j<=i) those would have been done before
			if f2 in index[f1]["checkedTextAgainst"]:	# (this check doesn't prevent i vs j then j vs i, since we're prepping the list
				continue				# here before actually processing any of them)
			args.append([dic,f1,f2,threshold])
			# things get weird when you try putting lists etc in the dict. instead, we store "file1 file2" pairs as the key
			dic[f1+" "+f2]=""

	print("kick off pool")
	try:
		p=Pool(processes=parallelWorkers)
		with p as pool:
			pool.map(dupeTextWorker,args)
	except KeyboardInterrupt:
		pass

	print("updating index from shared globals")
	#print(dic.keys())
	for k in dic.keys():	# TODO: somehow the index is not getting updated. WHY?
		if len(dic[k])==0:		# blank means this entry may not have been reached
			continue
		print("UPDATE",k)
		f1,f2=k.split()
		if dic[k]=="match":
			#print("match")
			index[f1]["matches"].append(f2)
			index[f2]["matches"].append(f1)
		#print("checked")
		index[f1]["checkedTextAgainst"].append(f2)
		index[f2]["checkedTextAgainst"].append(f1)

def dupeTextWorker(args):
	try:
		dic,f1,f2,threshold=args
		#print("compare",f1,"vs",f2)
		start=time.time()
		# if file 2 has fewer words, it's more efficient to scan through it instead! 
		text1=index[f1]["text"] ; words1=text1.split() ; len1=len(words1)
		text2=index[f2]["text"] ; words2=text2.split() ; len2=len(words2)
		if len2<len1:
			text1,text2=text2,text1
			words1,words2=words2,words1
			len1,len2=len2,len1
		# scan through chunks of words until we reach the end, or until we find something
		for i in range(len1-threshold):
			sub=" ".join(words1[i:i+threshold])
			if True in [ c in sub for c in ignoredCharsets ]:
			#if ";" in sub: # certain characters may indicate, for example, shared citations! 
				continue
			if sub in text2:
				print("likely match:",f1,f2)
				print(sub)
				#dic[f1]["matches"].append(f2)
				#dic[f2]["matches"].append(f1)
				dic[f1+" "+f2]="match"
				break
		# whether or not we found anything, denote that these two files have been compared. 
		# in checkForDuplicateTextSingle(), we update the index global directly, but we can't do that here. memory is not shared. instead, we write to the shared dict
		if len(dic[f1+" "+f2])==0:
			dic[f1+" "+f2]="nope"
		#time.sleep(1)
		took=time.time()-start
		if took>1:
			print(f1,"vs",f2,"took",took)
	except KeyboardInterrupt:
		pass

# extract an image of the middle page of both documents. if it is a pixel-by-pixel match, it's probably a copy. this is useful for pdfs without "text" stored in them (e.g. scans of books), which could probably benefit from OCR
def checkForDupesByImage(nth=1,i1=0,i2=0):
	global index
	imageDict={}
	files=list(sorted(index.keys()))
	
	for f1 in files[i1::nth]:
		print(f1)
		for f2 in tqdm(files[i2::nth]):
			# don't check self, or recheck ones we've already checked
			if f1==f2:
				continue
			if f2 in index[f1]["checkedPixelsAgainst"]:
				continue

			# get pixels from middle page for "this" file
			if f1 not in imageDict.keys():
				im=getMiddlePage(f1)
				imageDict[f1]=np.asarray(im)
			pix1=imageDict[f1] ; sy1,sx1,sc1=np.shape(pix1)

			if f2 not in imageDict.keys():
				im=getMiddlePage(f2)
				imageDict[f2]=np.asarray(im)
			pix2=imageDict[f2] ; sy2,sx2,sc2=np.shape(pix2)

			sy=min(sy1,sy2) ; sx=min(sx1,sx2)
			if np.amax(np.absolute(pix1[:sy,:sx,:]-pix2[:sy,:sx,:]))<2:
				print("likely match:",f1,f2)
				index[f1]["matches"].append(f2)
				index[f2]["matches"].append(f1)

			# whether or not we found anything, denote that these two files have been compared
			index[f1]["checkedPixelsAgainst"].append(f2)
			index[f2]["checkedPixelsAgainst"].append(f1)

# bonkers RAM usage to store the middle page of each pdf in memory (prevents needing to reload each every time). instead, compare subsets of all files against subsets
def checkForDupesByImageNested():
	N=3
	for i in range(N):					# all evens vs all evens
		for j in range(N):				# all odds vs all evens...
			checkForDupesByImage(nth=N,i1=i,i2=j)

# preview each file, and ask the user what they want to do (delete a duplicate, nmark them as not duplicates, etc)
# TODO how should we handle forked matches? A matched B and C, B only matched A, C only matched A (because B and C are pages out of A, for example). 
def manageDuplicates(ignoreAlreadySorted=True): 
	files=list(index.keys())
	for f in files:
		if ignoreAlreadySorted and "duplicates" in f: 			# Ignore files already in quarantine
			continue
		matches=list(sorted([f]+index[f]["matches"]))			# self + lookalikes
		matches=[ f1 for f1 in matches if "duplicate" not in f1 ]	# (ignore lookalikes in quarantine)
		if len(matches)>1:
			print(matches)
			command=" && ".join([ viewerCommand+" "+f+" > /dev/null 2>&1" for f in matches ])+" &"
			print(command)
			os.system(command)
			#for png in glob.glob("duplicates/preview/*.png"):
			#	os.remove(png)
			#for n,f1 in enumerate(matches):				# save off middle page preview image for each
			#	im=getMiddlePage(f1)
			#	im.save("duplicates/preview/"+str(n)+".png")
			c=input("shall we delete "+str(matches[1:])+"? (y/[integer]/i/u/e/w/q/help) : ")
			if "h" in c:
				print("y - yes: delete the second file, keep the first\n"+\
					"any integer: we will keep the file you specify and delete the rest\n"+\
					"i - ignore: ignore for now (you will be asked about these again)\n"+\
					"u - unmatch: unmatch all (you will not be asked about these again)\n"+\
					"e - edit: you will provide indices to regroup linkages\n"+\
					"w - wipe: wipe index for these entries so we can recheck for dupes\n"+\
					"q - quit")
				c=input("shall we delete "+str(matches[1:])+"? (y/[integer]/i/u/e/w/q/help) : ")
			if len(c)==0:
				return
			if "i" in c:						# "ignore for now" (just move on)
				continue
			elif "q" in c:						# exit
				return
			elif "w" in c:						# "wipe" index. unlinks for future rechecking as dupes
				unlinkEntries(filelist=matches,fromAll=False) 	# should we unlink from all other files too, or just within matches?
			elif "u" in c:						# unmatch all. none of these are duplicates
				unmatchEntries(matches) ; continue
			elif "e" in c:						# some sub-grouping of many might still be duplicates
				print(matches)
				chunks=[]
				while True:					# ask the user to specify the groupings
					c=input("enter indices (comma separated) to group: ")
					if "q" in c or len(c)==0:
						break
					chunk=[ int(v) for v in c.split(",") ]
					chunks.append(chunk)
				# TWO STRATEGIES: for each file in each chunk, nuke "matches" and rebuild with neighbors in the chunk
				# The problem then is incomplete matching search: 0->1,2,3, 1-->0,2,[3], 2-->0,1,[2], 3-->0,[1,2]
				# this could occur if 3 hasn't been checked and 1 is midway through.
				# if we're analyzing 3, we'll nuke 0's pointers and 1,2 will have danglers!
				# OR, for each item in a chunk, for each item NOT in that chunk, unmatch those two specificlly
				# 3 will still have no affiliation with 2, but they haven't been checked yet at least. 
				# furthermore, partial matches may exist. 1st half of 0 matches 1, 2nd half matches 3. so 1 doesn't actually match 3
				# we should not add links, we should only remove them!
				for chunk in chunks: 				# chunks might be: [[0,1],[2,3,4],[5]]
					names=[ matches[i] for i in chunk ]	# filenames of myself and my friends
					others=[ m for m in matches if m not in names ] # and all other files outside this chunk
					for n in names:
						for o in others:
							unmatchEntries([n,o])
					#for i1 in chunk:			# "0" was specified to go with "1", but not 2,3,4,5
					#	f1=matches[i1]			# get the corresponding filename
					#	index[f1]["matches"]=[]		
					#	for i2 in chunk:
					#		if i1==i2:
					#			continue
					#		f2=matches[i2]
					#		index[f1]["matches"].append(f2)

				#continue
			elif "y" in c or c in "0123456789":
				if "y" in c:
					c=0
				else:
					c=int(c)
				print("MOVE ALL BUT",c,matches[c])
				for n,f1 in enumerate(matches):		# deleta all EXCEPT the selected file
					if n==c:
						continue
					print("move",n,f1)
					f2="duplicates/"+f1.split("/")[-1]
					shutil.move(f1,f2)
					rekey(f1,f2)
					i=files.index(f1) ; files[i]=f2

# plausible we somehow(?) moved all copies of a given file into the dupes folder. that would be bad. 
def dupeSanityCheck():
	for k in index.keys():
		if "duplicates" not in k:
			continue
		for m in index[k]["matches"]:
			if "duplicates" not in m:
				break
		else:
			print("WATCH OUT!",f,"only has dupes in duplicates")

# given a filename, remove that filename's index entry's pointer to other files, AND, remove all other files' pointers to this file.
# useful for if, say, you ran with too loose a definition on text-based dupe matching, and have a bunch of false-positives. you may wish to manually purge the false-positives and re-run dupe-matching on them. 
def unlinkEntries(filelist='',fromAll=True):
	# query the user for filename(s)
	if len(filelist)==0:
		filelist=[]
		while True:
			c=input("enter filename to unlink: ")
			if c=="q" or len(c)==0:
				break
			filelist.append(c)
	# for every time in the filelist, EITHER compare against EVERY other file, or other files in this same filelist
	for c in filelist:
		if fromAll:
			others=list(index.keys())
		else:
			others=filelist
		for f in others:
			# for an index entry (pdf file), a dict stores pointers to other files. these are the locations of those pointers. so when we change a file's name or location, we need to check all other files' pointers and update them with this file's new name or location. 
			print("remove",c,"-->",f,"linkages")

			for pointerKey in ["matches","checkedTextAgainst","checkedPixelsAgainst"]: 
				if c in index[f][pointerKey]:
					i=index[f][pointerKey].index(c)
					del index[f][pointerKey][i]
		for pointerKey in ["matches","checkedTextAgainst","checkedPixelsAgainst"]:
			if c in index.keys():
				index[c][pointerKey]=[]

# gives in the list passed will no longer be considered duplicates
def unmatchEntries(filelist):
	for f1 in filelist:
		for f2 in filelist:
			if f1==f2:
				continue
			if f1 in index[f2]["matches"]:
				print(f2,"will no longer match",f1)
				i=index[f2]["matches"].index(f1)
				del index[f2]["matches"][i]

# look for files in the index with no text. run OCR (optical character recognition), and re-scan them for text
def findOCRable():
	global index
	yesToAll=False
	for f in index.keys():
		if len(index[f]["text"])<10:
			if not yesToAll:
				c=viewerCommand+" "+f+" > /dev/null 2>&1"
				os.system(c)
				c=input("file "+f+" might benefit from some OCR. do it? (y/n) : ")
			else:
				print("file "+f+" might benefit from some OCR. do it? (y/n) : [y]")
			if "a" in c:
				yesToAll=True
			if "y" in c or yesToAll:
				os.system("ocrmypdf "+f+" "+f)
				text=" ".join(getPdfText(f))
				index[f]["text"]=text
			if "q" in c:
				break

# e.g. if "authorname2013c.pdf" if the first rename to "authorname2013a.pdf" and so on
def reletter(): 
	files=list(sorted(index.keys())) ; authorsYears=[]
	# gather up author names from all files
	for f in files:
		f=f.split("/")[-1]			# exclude directory name
		for i in range(len(f)):
			if f[i] in "0123456789":
				break
		authorsYears.append( f[:i+4].lower() )
	# scan through files looking for files to rename
	for f in files:
		if index[f].get("dontrename",False):
			print(f,"[always skip]")
			continue
		if not os.path.exists(f):
			print(f,"[does not exist]")
			continue
		if "duplicates" in f:
			continue
		for i in range(len(f)):
			if f[i] in "0123456789":
				break
		else:
			continue
		author=f[:i].split("/")[-1].lower() ; year=f[i:i+4] ; letter=f[i+4:].replace(".pdf","")
		direc=""
		if "/" in f:
			direc="/".join(f.split("/")[:-1])+"/"
		if "si" in letter.lower() or "ocr" in f.lower():		# do not reletter supplemental info files! (we will look for them with the main one)
			print(f,"[ignore SI]")
			continue
		for letter in "abcdefghijklmnopqrstuvwxyz":
			if letter=="a" and authorsYears.count(author+year)==1:
				letter=""
			if direc+author+year+letter+".pdf"==f:	# self. filename is already fine
				print(f,"[okay]")
				break
			if direc+author+year+letter+".pdf" in index.keys():	# another file already has this letter
				continue
			c=input("rename: "+f+" --> "+direc+author+year+letter+".pdf (y/i/n) : ")
			if len(c)>3:
				while os.path.exists(c+".pdf"):
					c=input("error, that file already exists, try again: ")
				rekey(f,c+".pdf")
				shutil.move(f,c+".pdf")
			elif "y" in c:
				rekey(f,direc+author+year+letter+".pdf")
				shutil.move(f,direc+author+year+letter+".pdf")
			elif "n" in c:
				index[f]["dontrename"]=True
			elif "q" in c:
				return
			break
			#if os.path.exists

# manual rename (updates the index, rather than renaming via your file browser)
def rename():
	while True:
		f=input("enter filename: ")
		if len(f)==0 or f=="q":
			break
		if not os.path.exists(f):
			print("file does not exist")
			continue
		if f not in index.keys():
			print("file not in index")
			continue
		f2=input("rename to: ")
		if os.path.exists(f2):
			print("that file already exists")
			continue
		rekey(f,f2)
		shutil.move(f,f2)

# raw dump of a file's index entry
def inspectEntry():
	c=input("enter name: ")
	if c in index.keys():
		for k in index[c].keys():
			if k!="text":
				print(k,index[c][k])

# search through file index, allows boolean keys such as "&" (and) and "|" (or)
def textSearch():
	searchstring=input("enter search string (use & and | for bool logic) : ")
	if len(searchstring)==0:
		return
	# e.g. convert entered: pyrometer & (melt pool | molten)
	# into: "pyrometer" in s and ("melt pool" in s or "molten" in s)
	# so we can put the text from each paper into the variable "s", then "eval" the formatted search string
	formatted="" ; chunk=""
	for c in searchstring:
		if c in "()&|":							# control characters
			chunk=chunk.strip()					# don't leave dangling spaces around searched text (bult multi-word search text is okay)
			if len(chunk)>0:
				formatted=formatted+"\""+chunk+"\" in s"	# searchstring is surrounded by quotes
			chunk=""
			c={"(":"(",")":")","&":" and ","|":" or "}[c]		# make appropriate replacements for control characters (not necessary but improves readability imo)
			formatted=formatted+c
		else:
			chunk=chunk+c
	chunk=chunk.strip()
	if len(chunk)>0:							# finish up (don't leave off last search term if not followed by control character
		formatted=formatted+"\""+chunk+"\" in s"

	print(formatted)
	with open("tpBib-searchresults.txt",'w') as fo:
		for f in sorted(index.keys()):							# for each file, grab the text, and check it
			s=index[f]["text"]
			if eval(formatted):
				print(f)
				fo.write(f+"\n")

def getAuthorName(f):
	f=f.split("/")[-1]
	for i in range(len(f)):
		if f[i] in "0123456789.":
			break
	return f[:i].lower().strip()

lastOpened=False
# ask the user for a filename, with or without file suffix (.pdf), and return last-opened if none is entered
def getFilename():
	global lastOpened
	f=input("enter filename: ")
	if len(f)==0 and lastOpened:
		return lastOpened
	if ".pdf" not in f:
		f=f+".pdf"
	if not os.path.exists(f):
		print("error, file does not exist")
		candidates=[]
		authorName=getAuthorName(f)#.lower().strip()
		#print("authorName",authorName)
		for fc in sorted(index.keys()):
			fca=getAuthorName(fc)#.lower().strip()
			#print("compare against: ",authorName,fca,authorName==fca)
			if authorName in fca or fca in authorName:
				candidates.append(fc)
		if len(candidates)>0:
			print("did you mean: "+",".join(candidates))

		return False
	lastOpened=f
	return f

# ask for the filename, open it with the system's pdf viewer
def openFile():
	f=getFilename()
	if not f:
		return
	c=viewerCommand+" "+f+" > /dev/null 2>&1"
	os.system(c)

# ask for the filename, return getAuthorName(fc).lower()
def getBibtex():
	import pdf2bib
	pdf2bib.config.set('verbose',False)
	f=getFilename()
	if not f:
		return
	bib=pdf2bib.pdf2bib(f)['bibtex']
	print(bib)

def translatePaper():
	f=getFilename()
	text=index[f]["text"]

	import asyncio,time
	from googletrans import Translator
	async def translate_text():
		async with Translator() as translator:
			chunks=[[]]
			for word in text.split():
				if len(chunks[-1])>=100:
					chunks.append([])
				chunks[-1].append(word)
				#if len(chunks)>10:
				#	break
			chunks=[ " ".join(chunk) for chunk in chunks ]
			#print(chunks)
			translations = await translator.translate(chunks, dest='en')
			#translations=sum(translation)
			#print(translations)
			#print(" ".join(results))
			with open(f.replace(".pdf","_translated.txt"),'w') as fo:
				for n,translation in enumerate(translations):
					#print(n,chunks[n],translation.origin,translation.text)
					fo.write(translation.text)
	asyncio.run(translate_text())
	#translate_text()

	#print(result)
	#with open(f.replace(".pdf","_translated.txt"),'w') as fo:
	#	fo.write(str(result))


# "smart" command-line menu function: pass it a list of doubles: text and function to be called, and we'll display the text, and execute the function if that index is chosen
def menu(options,save=True):
	while True:
		s=["Options: (1,2,3,...q)"]+[ str(i+1)+") "+o[0] for i,o in enumerate(options) ]+[">>> "]
		c=input("\n".join(s))
		if "q" in c:
			if save:
				saveJson()
			return
		c=int(c)
		func=[ o[1] for o in options ][c-1]
		try:
			func()
		except KeyboardInterrupt:
			pass
		#saveJson()

def adminMenu():
	menu([["scan folder",indexing],
	["text-based dupe-check (single)",checkForDuplicateTextSingle],
	["text-based dupe-check (parallel)",checkForDuplicateTextParallel],
	["image-based dupe-check",checkForDupesByImageNested],
	["manage duplicates",manageDuplicates],
	["guided reletter",reletter],
	["find OCRable",findOCRable],
	["update timestamps in index",fixTimestamps],
	["manual unlink for rescan",unlinkEntries],
	["manual rename",rename],
	["inspect index entry",inspectEntry]])

menu([["search",textSearch],
	["open file",openFile],
	["get bibtex",getBibtex],
	["translate",translatePaper],
	["admin menu",adminMenu]],save=False)






