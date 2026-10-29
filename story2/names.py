"""Names that fit the cast (docs/TASKS_quality_overhaul.md task 3.16; audit 14.5): when the registry invents a person for a story told with an Indian cast, the name must be one an
Indian viewer would believe in that region, never "Sam Eriksen". Only invented people are renamed; a person the story names keeps the story's name. Given names only, no
surnames, so no caste or religion is implied."""
import hashlib
import re

MALE = {
    "generic": "Rahul Amit Sanjay Vijay Rajesh Suresh Anil Manoj Deepak Rakesh Ravi Arun Ashok Naveen Prakash Mahesh Dinesh Sunil Vikas Mohan Kiran Harish Sandeep Pankaj Naresh Ramesh Satish Yogesh Gopal Bharat Arjun Karan Rohit Nitin Ajay Vinod Kamal Lalit".split(),
    "punjab": "Gurpreet Harjit Manpreet Jaswinder Baljit Kuldeep Sukhdev Amarjit Balwinder Paramjit Gurmeet Jagdeep Harvinder".split(),
    "gujarat": "Jignesh Hitesh Kirit Bhavesh Paresh Mitesh Nilesh Dhaval Chirag Hardik Jayesh Kalpesh".split(),
    "mumbai": "Sachin Prashant Santosh Ganesh Vishal Amol Siddharth Nilesh Rohan Swapnil Tushar".split(),
    "kolkata": "Subrata Anirban Debashis Sourav Tapan Partha Arindam Soumen Abhijit Sudipto".split(),
    "south": "Karthik Venkatesh Murali Srinivas Anand Prasad Senthil Ganesan Harish Naveen Vignesh".split(),
    "up_hindi_belt": "Mukesh Brijesh Dharmendra Shivam Ashish Vivek Ramesh Pappu Sudhir Awadhesh Anurag".split(),
    "delhi": "Rohit Nikhil Gaurav Varun Ankit Mohit Sumit Kunal Manish Tarun".split(),
    "rajasthan": "Bhanwar Mahendra Narendra Dilip Hanuman Ganpat Devendra Rajendra".split(),
}
FEMALE = {
    "generic": "Priya Neha Anita Sunita Kavita Pooja Rekha Meena Shobha Usha Radha Seema Geeta Sita Anjali Nisha Kiran Asha Ritu Swati".split(),
    "punjab": "Simran Harpreet Jasleen Navneet Gurleen Manjit Kulwant Amandeep Sukhwinder".split(),
    "gujarat": "Hetal Bhavna Jayshree Dipti Kinjal Rupal Mital Nirali".split(),
    "mumbai": "Vaishali Archana Smita Manasi Sneha Rutuja Pallavi Apurva".split(),
    "kolkata": "Moumita Sumana Rina Mitali Debjani Suchitra Ananya Poulami".split(),
    "south": "Lakshmi Divya Revathi Kavitha Anitha Deepa Meenakshi Sowmya".split(),
    "up_hindi_belt": "Poonam Sarita Anju Pushpa Savitri Sangeeta Rani Munni".split(),
    "delhi": "Ritika Shweta Komal Preeti Sonia Anamika Pallavi Divya".split(),
    "rajasthan": "Gulab Kesar Sunita Mamta Lata Santosh Bhanwari".split(),
}
_ALL = {n.lower() for d in (MALE, FEMALE) for ns in d.values() for n in ns}
# first names of real Indian use that are not in the lists above but should never be renamed (and some very common ones)
_ALSO = set("raj kumar singh devi lal ram shyam krishna mohammad mohd ali khan ahmed imran salman faisal aarav vihaan aditya ishaan vivaan sai anaya aadhya diya ananya myra sara fatima aisha zoya".split())


def is_indian(name: str) -> bool:
    """A name that an Indian viewer would not find foreign: any name in Devanagari or another Indian script, or one whose first word is a known Indian given name. The lists are
    deliberately generous; an unknown Latin-script name counts as foreign and is replaced only when the person was invented."""
    first = (name or "").strip().split(" ")[0].lower().strip(".,'")
    if not first:
        return True
    if re.search(r"[^\x00-\u024f]", name):                      # a script other than Latin
        return True
    return first in _ALL or first in _ALSO or first.rstrip("ji") in _ALL


def suggest(regions: list[str], gender: str, taken: set[str], seed: str = "") -> str:
    """A given name for an invented person: from the story's region first, then the general list; never one already used in the film; the same seed gives the same name."""
    table = FEMALE if re.search(r"woman|female|girl|lady", gender or "", re.I) else MALE
    pool: list[str] = []
    for r in list(regions) + ["generic"]:
        pool += [n for n in table.get(r, []) if n not in pool]
    free = [n for n in pool if n.lower() not in {t.lower() for t in taken}] or pool
    return free[int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16) % len(free)]


def needs_rename(name: str) -> bool:
    """An invented person's name that should be replaced: a proper name (a capitalised word in Latin letters) that an Indian viewer would find foreign. A role such as "the trader"
    or "an old shopkeeper" is not a name and stays."""
    n = (name or "").strip()
    return bool(re.search(r"\b[A-Z][a-z]+", n)) and not re.match(r"(?i)(the|a|an|old|young|elderly|senior|junior|local|unnamed)\s", n) and not is_indian(n)
