import re

# Comprehensive list of standard English stop words and recruiter filler words
STOP_WORDS = {
    "a", "about", "above", "across", "after", "again", "against", "all", "almost", 
    "alone", "along", "alongside", "already", "also", "although", "always", "am", 
    "among", "an", "and", "another", "any", "anybody", "anyone", "anything", "apply", 
    "are", "area", "areas", "around", "as", "at", "be", "became", "because", "become", 
    "becomes", "been", "before", "began", "behind", "being", "below", "beside", "besides", 
    "best", "better", "between", "beyond", "both", "but", "by", "can", "cannot", "could", 
    "did", "do", "does", "doing", "done", "down", "during", "each", "either", "else", 
    "enough", "etc", "even", "ever", "every", "everyone", "everything", "everywhere", 
    "few", "find", "first", "for", "from", "further", "get", "give", "go", "good", 
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", 
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", 
    "just", "keep", "keeps", "kind", "knew", "know", "known", "knows", "large", "last", 
    "later", "latest", "least", "less", "let", "like", "likely", "made", "make", "makes", 
    "many", "may", "me", "might", "more", "most", "much", "must", "my", "myself", "near", 
    "need", "needs", "never", "new", "next", "no", "nobody", "none", "noone", "nor", 
    "not", "nothing", "now", "of", "off", "often", "on", "once", "one", "only", "onto", 
    "or", "other", "others", "our", "ours", "ourselves", "out", "over", "own", "part", 
    "per", "perhaps", "please", "put", "rather", "really", "said", "same", "say", "says", 
    "see", "seem", "seemed", "seeming", "seems", "several", "shall", "she", "should", 
    "show", "shows", "side", "since", "so", "some", "someone", "something", "sometime", 
    "still", "such", "take", "than", "that", "the", "their", "them", "themselves", "then", 
    "there", "these", "they", "thing", "things", "think", "thinks", "this", "those", 
    "though", "thought", "through", "throughout", "to", "together", "too", "under", 
    "until", "up", "upon", "us", "use", "used", "uses", "using", "very", "want", "wants", 
    "was", "we", "well", "went", "were", "what", "whatever", "when", "where", "whether", 
    "which", "while", "who", "whole", "whom", "whose", "why", "will", "with", "within", 
    "without", "would", "yet", "you", "your", "yours", "yourself", "yourselves",
    # Specific metric noise (e.g. "10m", "5yr")
    "10m", "additional", "annually", "aspects", "assistance", "background", "certain"
}

def extract_keywords(text: str) -> set:
    """Extract clean keywords, filtering out stop words, numbers, and short tokens."""
    if not text:
        return set()

    # Convert to lowercase and find all alphanumeric word tokens
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())

    # Filter out stop words and single/double character noise
    clean_words = {word for word in words if word not in STOP_WORDS and len(word) > 2}

    return clean_words

def calculate_ats_gap(cv_text: str, job_text: str) -> dict:
    """Calculate match score and keyword gap analysis."""
    cv_keywords = extract_keywords(cv_text)
    job_keywords = extract_keywords(job_text)

    if not job_keywords:
        return {
            "ats_score": 0.0,
            "hits": [],
            "gaps": []
        }

    hits = sorted(list(cv_keywords.intersection(job_keywords)))
    gaps = sorted(list(job_keywords.difference(cv_keywords)))

    score = (len(hits) / len(job_keywords)) * 100.0

    return {
        "ats_score": round(score, 1),
        "hits": hits,
        "gaps": gaps
    }