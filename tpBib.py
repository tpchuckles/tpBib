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
		return True
	except KeyboardInterrupt:								# dump failing for some other reason shoudn't retry indefinitely?
		print("WARNING: PLEASE DO NOT INTERRUPT JSON SAVE, OR ELSE YOUR DATABASE WILL BE CORRUPTED")
		return saveJson()
	except Exception as e:
		import traceback
		print(traceback.print_exc())
		return False

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

def indexed(f):
	global index
	timestamp=os.path.getmtime(f)
	text=" ".join(" ".join(getPdfText(f)).split())			# pull text from pdf (so we can search and deduplicate later)
	h = hashed(f)
	entry={ "text":text, "timestamp":timestamp, "hash":h, "checkedTextAgainst":[], "checkedPixelsAgainst":[], "matches":[] }
	index[f]=entry

# scan all folders/subfolders, check each file. if it's in the index, check the timestamp, ignore or update. if it's not, add it. check all index entries to see if there are extras. 
def indexing():
	files=glob.glob("**/*.pdf",recursive=True)				# collect up all files
	files = [ f for f in files if ".dupes/" not in f ]
	global index
	print("updating index")
	# ensure all files are in index
	for n,f in enumerate(sorted(files)):					# loop through files in folder
		# was file already indexed?
		timestamp=os.path.getmtime(f)					# get file modification time https://stackoverflow.com/questions/237079/how-do-i-get-file-creation-and-modification-date-times
		if f in index.keys() and index[f]["timestamp"]==timestamp:	# if file is unchanged, ignore
			continue
		# was the file indexed previously, but moved? previously we used a file base name, but we also want to capture renamed files, so check hash instead
		wasMoved=False
		h = hashed(f)
		for k in list(index.keys()):
			if h == index[k]["hash"] and timestamp==index[k]["timestamp"] and\
					not os.path.exists(k): # do not warn about movement if BOTH files exist
				print("looks like",k,"was moved to",f)
				wasMoved=True
				rekey(k,f)
				#index[f]=copyof(index[k])
				#del index[k]
				break
		if wasMoved:
			continue
		# or is it a new file! or timestamp changed
		print("adding",f,"to index:\t\t",n,"/",len(files))
		indexed(f)
		unlinkEntries([f]) # edge case: timestamp changed. cleanupIndex will not delete references from other files to this.

	cleanupIndex("matches",files) # oops, cleanup was not supposed to be inside the file loop (led to order-based purging)
	cleanupIndex("checkedTextAgainst",files)
	cleanupIndex("checkedPixelsAgainst",files)

def gatherFrom():
	global index
	where = input("enter path to directory to scrape: ")
	if len(where)==0:
		return
	files = glob.glob(where+"/*.pdf") ; failed = [] ; ignored = [] ; success = []
	already = [ index[f]["copied_from"] for f in index.keys() if "copied_from" in index[f].keys() ]
	print("hashing existing")
	hashes = { }
	for f in tqdm(list(sorted(index.keys()))):
		h = index[f]["hash"]
		hashes[ h ] = f
	# loop importable files
	for f in files:
		# To start, gnore any that have already been completed
		if f in already:
			ignored.append(f)
		h = hashed(f)
		if h in hashes.keys(): # TODO should add h to hashes in case there are dupes in the imported folder
			f2 = hashes[h]
			index[f2]["copied_from"]=f
			ignored.append(f)
			print("IDENTICAL FILE ALREADY FOUND",f)
			continue
		# First, try reading PDF metadata to scrape author/year
		try:
			meta=PdfReader(f).metadata
			author = meta.author
			if author is not None:
				print("PdfReader found author(s)",author)
				author = str(author).lower().split(",")[0].split()[-1] # first last, first last...
			year=str(meta.creation_date.year)
			print("PdfReader found year",year)
		except KeyboardInterrupt:
			break
		except Exception as e:
			print("meta errror",e) ; time.sleep(5)
			author = None ; year = None

		# If that fails, try pdf2bib. let's just hijack our existing getBibtex function
		try:
			if author is None or year is None:
				bib=getBibtex(f,ask=False)
				# it might fail outright
				if bib is None:
					print("bib error") ; time.sleep(5)
					failed.append(f)
					continue
				# or we can try to parse author/year from it
				for l in bib.split("\n"):
					# comparison against whitespace purged https://stackoverflow.com/questions/8270092/remove-all-whitespace-in-a-string
					if "year=" in "".join(l.split()):
						year = l.replace("year","").replace("=","").replace("{","").replace("}","").replace(",","").strip()
						print("bibtex found year",year)
					if "author=" in "".join(l.split()):
						print("author line found:",l)
						authors = l.replace("author","").replace("=","").replace("{","").replace("}","").strip()
						first = authors.split("and")[0].strip()
						# handle both "Last, First" and "First Last" formatting
						author = first.split(",")[0].split()[-1].lower()
						print("bibtex found author",author)
		except KeyboardInterrupt:
			break
		except Exception as e:
			print("bib fail",e) ; time.sleep(5)
			author = None ; year = None

		if author is None or year is None:
			failed.append(f)
			continue
		if not author or not year:
			failed.append(f)
			continue

		try:
			# if both found, loop through firstauthorlastnameYEARa.pdf
			suffixes=" abcdefghijklmnopqrstuvwxyz"
			suffix = "" ; i=0
			while os.path.exists(author+year+suffix+".pdf"):
				i+=1
				suffix = suffixes[i]
			f2 = author+year+suffix+".pdf"
			shutil.copy(f,f2)

			indexed(f2)
			index[f2]["copied_from"]=f
			success.append(f)
		except KeyboardInterrupt:
			break
		except Exception as e:
			print("shutil error",e) ; time.sleep(5)
			failed.append(f)
			continue
	print("copied in "+str(len(success))+"/"+str(len(files))+" files, "+str(len(failed))+" failed, "+str(len(ignored))+" ignored.")
	for f in failed:
		print(f)
	print("recommended to rerun indexing just to be safe")
	#if len(failed)>0:
	#	for
	#	print("failed on: "+",".join(skipped))

def cleanupIndex(pointerKey,files):
	# ensure all index entries exist as files! 
	for f in list(index.keys()):							# look through files in index
		if f not in files:						# clear index entries for files which are no longer present
			del index[f]
			print("removing missing file",f,"from index")
	# also perform a sanity check on index entries
	for f in list(index.keys()):
		if f in index[f][pointerKey]:
			print("removing self-"+pointerKey+":",f,"-->",f)
			i=index[f][pointerKey].index(f)
			del index[f][pointerKey][i]
		for f2 in list(index[f][pointerKey]):
			if f2 not in index.keys():
				print("removing dangling "+pointerKey+":",f,"-->",f2)
				i=index[f][pointerKey].index(f2)
				del index[f][pointerKey][i]
		if len(set(index[f][pointerKey])) != len(index[f][pointerKey]):
			print("removing duplicate "+pointerKey+" entries:",index[f][pointerKey])
			index[f][pointerKey]=list(set(index[f][pointerKey]))

def hashed(f):
	import hashlib
	hasher = hashlib.sha256()
	return hashlib.file_digest(open(f, "rb"), "sha256").hexdigest()

def addMatch(f1,f2):
	if f2 not in index[f1]["matches"]:
		index[f1]["matches"].append(f2)
	if f1 not in index[f2]["matches"]:
		index[f2]["matches"].append(f1)

def checkForBinaryIdentical():
	global index
	os.makedirs(".dupes",exist_ok=True)
	print("hashing")
	hashes = { }
	fnames = list(sorted(index.keys()))
	for f in tqdm(fnames):
		h = index[f]["hash"]
		hashes[f] = h
	print("comparing hashes")
	for i,f1 in enumerate(tqdm(fnames)):
		for j,f2 in enumerate(fnames):
			if i>=j:
				continue
			if not os.path.exists(f2):
				continue
			if hashes[f1]==hashes[f2]:
				#shutil.move(f2,".dupes/"+f2.replace("/","_"))
				#del index[f2]
				print("likely match:",f1,f2)
				addMatch(f1,f2)

# for string-based dupe-checking, prevent certain frequently-occurring long strings from matching: exclude common license blurbs, data availability statements, long affiliation addresses, repeated references, pre-print or author proof watermarks. These are allowed to be pretty agressive: if we have two matching papers but a portion of a matching paragraph is excluded, hopefully the rest of the paper is the same so we'll still match later.
ignoredCharsets=[";","(",")"]+list("0123456789")+\
	[ " "+l+". " for l in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" ]+\
		["creative", "license", "licence", "summary", "permission", "distribution", "reproduction", "party", "article", "availability", "USA", "United", "Canada", "Department", "University", "Press","accepted","proof","publication","reviewed","manuscript"]
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
				if True in [ c.lower() in sub.lower() for c in ignoredCharsets ]:
					continue
				if sub in text2:
					print("likely match:",f1,f2)
					print(sub)
					addMatch(f1,f2)
					break

			# whether or not we found anything, denote that these two files have been compared
			index[f1]["checkedTextAgainst"].append(f2)
			index[f2]["checkedTextAgainst"].append(f1)

# parallelized: works the same as checkForDuplicatesSingle, but using a multiprocessing pool
def checkForDuplicateTextParallel(threshold=consecutiveWordThreshold):
	global index

	from multiprocessing import Pool, Process, Manager, set_start_method #, Array, Value
	set_start_method('fork',force=True)
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
			dic[(f1,f2)]="" # tuples can be keys! better than splitting by " ", in case there are spaces in paths/filenames

	print("kick off pool",len(args),"checks across",parallelWorkers,"workers")
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
		f1,f2=k
		if dic[k]=="match":
			#print("match")
			addMatch(f1,f2)
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
			sub=" ".join(words1[i:i+threshold]) # sliding window "the quick [brown fox jumped over] the lazy dog"
			if True in [ c in sub for c in ignoredCharsets ]:
			#if ";" in sub: # certain characters may indicate, for example, shared citations! 
				continue
			if sub in text2:					# sliding window from above, compared to full second text
				print("likely match:",f1,f2)
				print(sub)
				dic[(f1,f2)]="match"
				break
		# whether or not we found anything, denote that these two files have been compared. 
		# in checkForDuplicateTextSingle(), we update the index global directly, but we can't do that here. memory is not shared. instead, we write to the shared dict
		if len(dic[(f1,f2)])==0:
			dic[(f1,f2)]="nope"
		#time.sleep(1)
		took=time.time()-start
		if took>1:
			print(f1,"vs",f2,"took",took)
	except KeyboardInterrupt:
		pass

def checkForDupesByImage():
	import hashlib
	hasher = hashlib.sha256()
	global index ; hashes = {}
	print("extracting and hashing images")
	fnames = list(sorted(index.keys()))
	for f in tqdm(fnames):
		im=getMiddlePage(f)
		h = hashlib.sha256(im.tobytes()).hexdigest()
		hashes[f]=h
	print("comparing hashes")
	for i,f1 in enumerate(tqdm(fnames)):
		for j,f2 in enumerate(fnames):
			if i>=j:
				continue
			if not os.path.exists(f2):
				continue
			if hashes[f1]==hashes[f2]:
				#shutil.move(f2,".dupes/"+f2.replace("/","_"))
				#del index[f2]
				print("likely match:",f1,f2)
				addMatch(f1,f2)


# extract an image of the middle page of both documents. if it is a pixel-by-pixel match, it's probably a copy. this is useful for pdfs without "text" stored in them (e.g. scans of books), which could probably benefit from OCR
def checkForDupesByImage_old(nth=1,i1=0,i2=0):
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
				addMatch(f1,f2)

			# whether or not we found anything, denote that these two files have been compared
			index[f1]["checkedPixelsAgainst"].append(f2)
			index[f2]["checkedPixelsAgainst"].append(f1)

# bonkers RAM usage to store the middle page of each pdf in memory (prevents needing to reload each every time). instead, compare subsets of all files against subsets
def checkForDupesByImageNested():
	N=20								# if N is too high, you reread images a ton of times. if N is too small you blow RAM
	for i in range(N):					# all evens vs all evens
		for j in range(N):				# all odds vs all evens...
			checkForDupesByImage(nth=N,i1=i,i2=j)

# preview each file, and ask the user what they want to do (delete a duplicate, nmark them as not duplicates, etc)
# TODO how should we handle forked matches? A matched B and C, B only matched A, C only matched A (because B and C are pages out of A, for example). 
def manageDuplicates(ignoreAlreadySorted=True): 
	files=[] ; num_matches = []
	for f in index.keys():
		files.append(f) ; num_matches.append(len(index[f]["matches"]))
	num_matches,files = zip(*reversed(sorted(zip(num_matches,files))))


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
				print("y   - yes: delete the second file, keep the first\n"+\
					"[n] - we will keep the file you specify and delete the rest\n"+\
					"i   - ignore: ignore for now (you will be asked about these again)\n"+\
					"u   - unmatch: unmatch all (you will not be asked about these again)\n"+\
					"e   - edit: you will provide indices to regroup linkages\n"+\
					"w   - wipe: wipe index for these entries so we can recheck for dupes\n"+\
					"q   - quit")
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
			if c=="*": # UNLINK ALL! use with care!
				filelist=list(index.keys())
			else:
				candidates = fuzzyMatch(c)
				if len(candidates)==1:
					filelist.append(candidates[0])
				else:
					print("did you mean",candidates)
	#filtered = []
	#for f in filelist:
	#	candidates = fuzzyMatch(f)
	#	if len(candidates)==1:
	#		filtered.apend(f)
	#	else:
	#		print("did you mean",candidates)
	#	#if ".pdf" not in f:
	#	#	f=f+".pdf"
	#	#if f not in index.keys():
	#	#	print("warning:",f,"not in index, did you mean ")
	#filelist = [ f if ".pdf" in f else f+".pdf" for f in filelist ]
	#filelist = filtered
	# for every time in the filelist, EITHER compare against EVERY other file, or other files in this same filelist
	for c in filelist:
		if fromAll:
			others=list(index.keys())
		else:
			others=filelist
		for f in others:
			# for an index entry (pdf file), a dict stores pointers to other files. these are the locations of those pointers. so when we change a file's name or location, we need to check all other files' pointers and update them with this file's new name or location. 
			removed = False
			for pointerKey in ["matches","checkedTextAgainst","checkedPixelsAgainst"]: 
				if c in index[f][pointerKey]:
					i=index[f][pointerKey].index(c)
					del index[f][pointerKey][i]
					removed = True
			if removed:
				print("remove",c,"-->",f,"linkages")
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
			f2 = direc+author+year+letter+".pdf"
			if f2 in index.keys() or os.path.exists(f2):	# another file already has this letter
				continue
			c=input("rename: "+f+" --> "+f2+" (y/i/n) : ")
			if len(c)>3:
				while os.path.exists(c+".pdf"):
					c=input("error, that file already exists, try again: ")
				rekey(f,c+".pdf")
				shutil.move(f,c+".pdf")
			elif "y" in c:
				rekey(f,f2)
				if f.lower() == f2:
					os.rename(f,f.replace(".pdf","_.pdf"))
					os.rename(f.replace(".pdf","_.pdf"),f2)
				else:
					os.rename(f,f2) # BUG: if only renaming is capitalization, and filesystem is case-insensitive, you will rekey but not actually rename. it will be reindex, all linkages will be removed (appearing as danglers), and it will be rechecked as dupe against everything.
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

def getYear(f):
	year = ""
	f=f.split("/")[-1]
	for i in range(len(f)):
		if f[i] in "0123456789":
			year += f[i]
	if len(year)==4:
		return year
	return None

def fuzzyMatch(f):
	if ".pdf" not in f:
		f=f+".pdf"
	# exact match, return it
	if f in index.keys():
		return [f]
	candidates=[]
	# empty filename??
	if len(f.strip())==0:
		return []
	# fuzzy-match by author name
	authorName=getAuthorName(f)#.lower().strip()
	for fc in sorted(index.keys()):
		fca=getAuthorName(fc)#.lower().strip()
		if authorName in fca or fca in authorName:
			candidates.append(fc)
	# if year is provide, filter down to year matches. cahill1990 candidates should limit to cahill1990a and cahill1990b, NOT cahill2004
	year = getYear(f)
	if year is not None:
		year_matches = [ getYear(f2)==year for f2 in candidates ]
		candidates = [ c for m,c in zip(year_matches,candidates) if m ]
	return candidates

last_opened=False
# ask the user for a filename, with or without file suffix (.pdf), and return last-opened if none is entered
def getFilename():
	global last_opened
	f=input("enter filename: ")
	# no file given, default to last
	if len(f)==0 and last_opened:
		return last_opened
	if ".pdf" not in f:
		f=f+".pdf"
	# exact match
	if os.path.exists(f):
		last_opened=f
		return f
	# fallback to fuzzy matching to find candidates
	print("error, file does not exist")
	candidates = fuzzyMatch(f)
	# one candidate, this is it
	if len(candidates)==1:
		print("assuming you meant: "+candidates[0])
		last_opened = candidates[0]
		return candidates[0]
	# multiple candidates, but one (and only one) is an exact author match
	author_matches = [ 1 if getAuthorName(f2)==f.replace(".pdf","") else 0 for f2 in candidates ]
	if sum(author_matches)==1:
		i = author_matches.index(1)
		print("assuming you meant: "+candidates[i])
		last_opened = candidates[i]
		return candidates[i]
	# more than one, we give up
	if len(candidates)>0:
		print("did you mean: "+",".join(candidates))
		return False

# ask for the filename, open it with the system's pdf viewer
def openFile():
	f=getFilename()
	if not f:
		return
	c=viewerCommand+" "+f+" > /dev/null 2>&1"
	os.system(c)

# ask for the filename, return getAuthorName(fc).lower()
def getBibtex(f="",ask=True):
	import pdf2bib
	pdf2bib.config.set('verbose',True)
	if len(f)==0:
		f=getFilename()
	if not f:
		return
	if f in index.keys() and "bibtex" in index[f].keys():
		bib=index[f]["bibtex"]
	else:
		bib=pdf2bib.pdf2bib(f).get('bibtex',None)
		if bib is None and ask:
			c=input("bibtex could not be generated. enter it manually? (y/n): ")
			if "y" in c.lower():
				enterBibtex()
		elif bib is None:
			return None
		else:
			lines=bib.split("\n")
			f2=f[0].upper()+f[1:].replace(".pdf","")
			lines[0]=lines[0].split("{")[0]+"{"+f2+","
			bib="\n".join(lines)
	print(bib)
	# pdf2doi can apparently edit the file, so rehash. indexed(f) updates the index, so copy off, update, re-write
	if f in index.keys():
		ind = index[f]
		indexed(f)
		for k in ind.keys():
			if k!="hash" and k!="timestamp":
				index[f][k]=ind[k]
	return bib

def enterBibtex():
	global index
	f=getFilename()
	if not f:
		return
	bib=[] ; print("enter bibxtex: \n")
	while True:
		#print("")
		b=input("")
		if b=="c":
			print("clearing bibtex")
			if "bibtex" in index[f].keys():
				del index[f]["bibtex"]
			break
		if b=="q":
			return
		if b and len(b)>2:
			bib.append(b)
		else:
			break
	#bib=input("enter bibtex: ")
	#if b=="c":
	#	print("clearing bibtex")
	#	if "bibtex" in index[f].keys():
	#		del index[f]["bibtex"]
	#	return
	#if b=="q":
	#	return
	index[f]["bibtex"]="\n".join(bib)
	saveJson()

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

def bib2xml(bibtex):
	import xml.etree.ElementTree as ET
	from xml.dom import minidom
	import bibtexparser
	bibtex = bibtexparser.loads(bibtex)

	root = ET.Element("bibliography")

	for entry in bibtex.entries:
		# Create an element for each entry type (e.g., <article>, <book>)
		entry_type = entry.get('ENTRYTYPE', 'entry')
		entry_element = ET.SubElement(root, entry_type)

		# Set the unique citation key as an attribute
		if 'ID' in entry:
			entry_element.set('id', entry['ID'])

		# Populate fields (e.g., <author>, <title>, <year>)
		for field_name, field_value in entry.items():
			# Skip internal metadata keys used by bibtexparser
			if field_name in ['ENTRYTYPE', 'ID']:
				continue

			field_element = ET.SubElement(entry_element, field_name)
			field_element.text = field_value

	xml_string = ET.tostring(root, encoding='utf-8')
	parsed_string = minidom.parseString(xml_string)
	pretty_xml = parsed_string.toprettyxml(indent="    ")

	#with open(xml_file_path, 'w', encoding='utf-8') as xml_file:
	#	xml_file.write(pretty_xml)
	print(pretty_xml)

# "smart" command-line menu function: pass it a list of doubles: text and function to be called, and we'll display the text, and execute the function if that index is chosen
def menu(options,save=True):
	while True:
		s=["Options: (1,2,3,...q)"]+[ str(i+1)+") "+o[0] for i,o in enumerate(options) ]+[">>> "]
		c=input("\n".join(s))
		if "q" in c:
			if save:
				if saveJson():
					return
				else:
					continue
			return
		try:
			c=int(c)
			func=[ o[1] for o in options ][c-1]
			func()
		except KeyboardInterrupt:
			continue
		except Exception as e:
			import traceback
			print(traceback.print_exc())

def adminMenu():
	menu([["scan folder",indexing],
	["gather from",gatherFrom],
	["hash-based dupe-check",checkForBinaryIdentical],
	["text-based dupe-check (single)",checkForDuplicateTextSingle],
	["text-based dupe-check (parallel)",checkForDuplicateTextParallel],
	["image-based dupe-check",checkForDupesByImage],
	["manage duplicates",manageDuplicates],
	["guided reletter",reletter],
	["find OCRable",findOCRable],
	["update timestamps in index",fixTimestamps],
	["manual unlink for rescan",unlinkEntries],
	["manual rename",rename],
	["manual enter bibtex",enterBibtex],
	["inspect index entry",inspectEntry]])

menu([["search",textSearch],
	["open file",openFile],
	["get bibtex",getBibtex],
	["translate",translatePaper],
	["admin menu",adminMenu]],save=False)






