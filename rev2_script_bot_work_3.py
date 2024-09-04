import os
import argparse
from dotenv import load_dotenv
import openai
import requests
from bs4 import BeautifulSoup
from base64 import b64encode
import logging
import json
import xml.etree.ElementTree as ET
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.DEBUG)

# Load environment variables
load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')
repo = os.getenv('GITHUB_REPO')
token = os.getenv('GITHUB_TOKEN')

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def get_articles_from_rss(feed_url, num_articles):
    response = requests.get(feed_url, headers=headers)
    articles = []
    if response.status_code == 200:
        root = ET.fromstring(response.content)
        for item in root.findall('.//item')[:num_articles]:
            title = item.find('title').text
            link = item.find('link').text
            articles.append({'title': title, 'link': link})
    else:
        logging.error(f"Error fetching RSS feed: {response.status_code}")
    logging.debug(f"Fetched {len(articles)} articles from {feed_url}")
    return articles

def fetch_article_body(url, body_selector):
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        article_body = soup.select_one(body_selector)
        return article_body.get_text(separator="\n").strip() if article_body else "Article body not found."
    except requests.RequestException as e:
        logging.error(f"Error fetching article body from '{url}': {e}")
        return f"Error fetching article body from '{url}': {e}"

def summarize_and_analyze(article):
    try:
        article_body = fetch_article_body(article['link'], article['body_selector'])
        prompt = f"Analyze the following article and detail: 1) what happened, 2) why it matters, and 3) what actions should be taken as a result of this information. Keep each answer around 100 words. Avoid mandate language like must and shall. Answer each question in paragraph format. :\nTitle: {article['title']}\nURL: {article['link']}\nContent:\n{article_body}"
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert cybersecurity assurance analyst seeking to brief a large US County's information security steering committee on current cybersecurity events."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500
        )
        logging.debug(f"Generated summary for article: {article['title']}")
        return response.choices[0].message['content']
    except openai.error.OpenAIError as e:
        logging.error(f"Error generating summary for article '{article['title']}': {e}")
        return f"Error generating summary for article '{article['title']}': {e}"

def post_to_github(repo, path, message, content, token):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "message": message,
        "content": b64encode(content.encode()).decode()
    }
    try:
        response = requests.put(url, headers=headers, json=data)
        response.raise_for_status()
        logging.debug(f"Posted to GitHub: {path}")
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Error posting to GitHub: {e}")
        return {}

def main(num_articles, source):
    articles = []
    if source in ('both', 'bleepingcomputer'):
        logging.info(f"Fetching {num_articles} articles from BleepingComputer RSS feed...")
        articles_from_bc = get_articles_from_rss("https://www.bleepingcomputer.com/feed/", num_articles)
        for article in articles_from_bc:
            article['body_selector'] = 'div.articleBody'
        articles += articles_from_bc
    if source in ('both', 'darkreading'):
        logging.info(f"Fetching {num_articles} articles from DarkReading RSS feed...")
        articles_from_dr = get_articles_from_rss("https://www.darkreading.com/rss.xml", num_articles)
        for article in articles_from_dr:
            article['body_selector'] = 'div.ArticleBase-BodyContent_Article'
        articles += articles_from_dr

    logging.debug(f"Total articles fetched: {len(articles)}")

    # Ensure local_summaries directory exists
    if not os.path.exists('local_summaries'):
        os.makedirs('local_summaries')

    current_date = datetime.now().strftime('%Y-%m-%d')
    for i, article in enumerate(articles):
        logging.info(f"Summarizing and analyzing article: {article['title']}")
        summary_analysis = summarize_and_analyze(article)
        timecode = datetime.now().strftime('%H%M%S')
        blog_content = f"Original Article: {article['link']}\n\n{summary_analysis}"
        path = f"{current_date}/post_{timecode}.md"
        logging.info(f"Posting summary and analysis to GitHub: {path}")
        response = post_to_github(repo, path, "Adding new blog post", blog_content, token)
        logging.info(f"GitHub response: {response}")

        # Write summary and metadata to a local file
        metadata = {
            "title": article['title'],
            "link": article['link'],
            "summary": summary_analysis
        }
        file_path = f"local_summaries/post_{timecode}.json"
        with open(file_path, 'w') as file:
            json.dump(metadata, file, indent=4)
        logging.info(f"Wrote summary and metadata to file: {file_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch, summarize, and post articles to GitHub.")
    parser.add_argument('-n', '--num_articles', type=int, default=5, help="Number of articles to fetch (default: 5)")
    parser.add_argument('-s', '--source', choices=['bleepingcomputer', 'darkreading', 'both'], default='both', help="Source of articles (default: both)")
    args = parser.parse_args()

    main(args.num_articles, args.source)

