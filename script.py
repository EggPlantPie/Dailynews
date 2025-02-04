import os
import yfinance as yf
import requests
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import openai
import json

# Configuration dictionary
CONFIG = {
    'company': {
        'name': 'Nvidia',
        'ticker': 'NVDA',
        'keywords': [
            'AI', 'artificial intelligence',
            'technology',
            'innovation',
        ],
        'news_domains': [
            'techcrunch.com',
            'theverge.com',
            'wired.com',
            'cnet.com',
            'engadget.com',
            'arstechnica.com',
            'zdnet.com',
            'venturebeat.com',
            'reuters.com',
            'bloomberg.com'
        ],
        'news_settings': {
            'from_date': '2025-02-01',  # Format: YYYY-MM-DD
            'max_days_old': 3  # Alternative: maximum age of news in days
        }
    },
    'api_keys': {
        'news_api': os.environ.get('NEWS_API_KEY'),
        'openai_api': os.environ.get('OPENAI_API_KEY')
    },
    'email': {
        'sender': os.environ.get('EMAIL_SENDER'),
        'password': os.environ.get('EMAIL_PASSWORD'),
        'recipient': os.environ.get('EMAIL_RECIPIENT')
    }
}

def get_stock_info(ticker):
    print(f"Starting stock info retrieval for {ticker}...")
    stock = yf.Ticker(ticker)
    
    try:
        print("Attempting to get stock history...")
        history = stock.history(period="5d")
        print(f"Raw history data:\n{history}")
        
        if history.empty:
            print(f"No price data found for {ticker}. Please verify the ticker symbol.")
            return None
            
        if len(history) < 2:
            current_price = history['Close'].iloc[-1]
            previous_close = current_price
        else:
            current_price = history['Close'].iloc[-1]
            previous_close = history['Close'].iloc[-2]
        
        price_change = current_price - previous_close
        price_change_percent = (price_change / previous_close) * 100
        
        return {
            'current_price': current_price,
            'price_change': price_change,
            'price_change_percent': price_change_percent
        }
        
    except Exception as e:
        print(f"Error getting stock info: {e}")
        return None

def get_company_news(company_config):
    """Get company news with date filtering."""
    # Construct query from company keywords
    keywords = company_config['keywords']
    keyword_query = ' OR '.join([f'"{kw}"' for kw in keywords])
    query = f'{company_config["name"]} AND ({keyword_query})'
    
    domains = ','.join(company_config['news_domains'])
    
    # Add date filtering
    news_settings = company_config.get('news_settings', {})
    if 'from_date' in news_settings:
        from_date = news_settings['from_date']
    else:
        # Default to last N days if no specific date is set
        max_days = news_settings.get('max_days_old', 3)
        from_date = (datetime.now() - timedelta(days=max_days)).strftime('%Y-%m-%d')
    
    url = (
        f'https://newsapi.org/v2/everything'
        f'?q={query}'
        f'&language=en'
        f'&sortBy=publishedAt'
        f'&pageSize=15'
        f'&domains={domains}'
        f'&from={from_date}'  # Add date filter
        f'&apiKey={CONFIG["api_keys"]["news_api"]}'
    )
    
    try:
        response = requests.get(url)
        news_data = response.json()
        
        if news_data['status'] != 'ok':
            print(f"Error from NewsAPI: {news_data.get('message', 'Unknown error')}")
            return []
        
        articles = []
        for article in news_data['articles']:
            if not all(key in article for key in ['title', 'url', 'source', 'description']):
                continue
            
            # Add published date to the article info
            published_at = article.get('publishedAt', '')
            if published_at:
                try:
                    published_date = datetime.strptime(published_at, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    published_date = published_at
            else:
                published_date = 'Date unknown'
            
            articles.append({
                'title': article['title'],
                'url': article['url'],
                'source': article['source']['name'],
                'description': article.get('description', ''),
                'published_at': published_date
            })
        
        # Sort articles by publication date (newest first)
        articles.sort(key=lambda x: x['published_at'], reverse=True)
        
        return analyze_articles_with_gpt(articles, company_config['name'])
        
    except Exception as e:
        print(f"Error fetching news: {e}")
        return []

def analyze_articles_with_gpt(articles, company_name):
    articles_text = "\n\n".join([
        f"Title: {article['title']}\n"
        f"Source: {article['source']}\n"
        f"Description: {article.get('description', 'No description available')}"
        for article in articles
    ])
    
    prompt = f"""
    As an AI expert in technology news analysis, review these news articles about {company_name} and select the 5 most relevant articles.
    
    Selection criteria:
    1. Focus on {company_name}'s technology initiatives and innovations
    2. Prioritize significant technological developments or announcements
    3. Ensure diversity in coverage (avoid multiple articles about the same topic)
    4. Prefer articles from different reliable sources
    5. Prioritize articles with substantial technical content over general business news
    
    Here are the articles:
    {articles_text}
    
    Please analyze these articles and return your selection in the following JSON format:
    {{
        "selected_articles": [
            {{
                "index": <original_article_index>,
                "reason": "Brief explanation of why this article was selected"
            }}
        ]
    }}
    Only include the JSON output, no additional text or formatting.
    """
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an AI expert in technology news analysis. Respond only with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        selection = json.loads(response.choices[0].message.content)
        selected_articles = []
        for item in selection['selected_articles']:
            index = item['index']
            if index < len(articles):
                article = articles[index].copy()
                article['selection_reason'] = item['reason']
                selected_articles.append(article)
        
        return selected_articles
        
    except Exception as e:
        print(f"Error in GPT analysis: {e}")
        return articles[:5]

def generate_news_summary(articles, company_name):
    """
    Generate a bullet-point summary with one point per selected news article.
    """
    articles_text = "\n\n".join([
        f"Title: {article['title']}\n"
        f"Source: {article['source']}\n"
        f"Description: {article.get('description', '')}"
        for article in articles
    ])
    
    prompt = f"""
    As a tech analyst, create a bullet-point summary of the key {company_name} technology developments, with one bullet point per news article.

    {articles_text}

    Please provide:
    • One bullet point per article (up to {len(articles)} points)
    • Each point should capture the key technical development or announcement
    • Keep each bullet point concise (1-2 lines)
    • Focus on concrete developments and technical implications
    • Keep the tone professional and analytical
    • Skip articles that are redundant or not technically significant

    Format each bullet point with "•" and return only the bullet points, one per line.
    If there is only one significant article, one bullet point is sufficient.
    """
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": f"You are a technology analyst specializing in {company_name}'s technical developments. Create concise, focused bullet points."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating summary: {e}")
        return None

def create_email_content(company_config, stock_info, news_articles):
    company_name = company_config['name']
    ticker = company_config['ticker']
    
    is_up = stock_info['price_change'] > 0
    color = "green" if is_up else "red"
    arrow = "▲" if is_up else "▼"
    
    summary = generate_news_summary(news_articles, company_name)
    
    if summary:
        bullet_points = [point.strip() for point in summary.split('•') if point.strip()]
        formatted_points = ''.join([
            f'<li style="margin-bottom: 10px; line-height: 1.6;">{point}</li>'
            for point in bullet_points
        ])
        summary_html = f'<ul style="list-style-type: none; padding-left: 0; margin: 0;">{formatted_points}</ul>'
    else:
        summary_html = f"No key developments available for today's {company_name} news."
    
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #333; border-bottom: 2px solid #ddd; padding-bottom: 10px;">
            {company_name} ({ticker}) Daily Update - {datetime.now().strftime('%B %d, %Y')}
        </h2>
        
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <h3 style="color: #333; margin-top: 0;">Stock Information</h3>
            <p style="font-size: 24px; margin: 10px 0;">
                <strong>${stock_info['current_price']:.2f}</strong>
                <span style="color: {color};">
                    {arrow} ${abs(stock_info['price_change']):.2f} ({stock_info['price_change_percent']:.2f}%)
                </span>
            </p>
        </div>
        
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <h3 style="color: #333; margin-top: 0;">Key Developments</h3>
            <div style="color: #444;">
                {summary_html}
            </div>
        </div>
        
        <div style="margin: 20px 0;">
            <h3 style="color: #333;">Latest News</h3>
            <div style="border: 1px solid #ddd; border-radius: 5px;">
    """
    
    for i, article in enumerate(news_articles):
        border_style = "" if i == len(news_articles)-1 else "border-bottom: 1px solid #ddd;"
        reason = article.get('selection_reason', '')
        published_at = article.get('published_at', '')
        html_content += f"""
                <div style="padding: 15px; {border_style}">
                    <p style="margin: 0;">
                        <strong style="color: #666;">{article['source']}</strong>
                        <span style="color: #888; font-size: 12px; float: right;">
                            {published_at}
                        </span><br>
                        <a href="{article['url']}" style="color: #0366d6; text-decoration: none; font-size: 16px;">
                            {article['title']}
                        </a>
                        {f'<br><span style="color: #666; font-size: 14px; font-style: italic;">{reason}</span>' if reason else ''}
                    </p>
                </div>
        """
    
    html_content += """
            </div>
        </div>
        
        <div style="color: #666; font-size: 12px; margin-top: 30px; padding-top: 10px; border-top: 1px solid #ddd;">
            <p>This is an automated email. Please do not reply.</p>
        </div>
    </body>
    </html>
    """
    
    return html_content

def send_email(email_config, company_config, html_content):
    # Set up email
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"{company_config['name']} Daily Update - {datetime.now().strftime('%Y-%m-%d')}"
    msg['From'] = email_config['sender']
    msg['To'] = email_config['recipient']
    
    # Attach HTML content
    msg.attach(MIMEText(html_content, 'html'))
    
    # Send email using Gmail SMTP
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(email_config['sender'], email_config['password'])
            server.send_message(msg)
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")

def main():
    # Initialize OpenAI
    openai.api_key = CONFIG['api_keys']['openai_api']
    
    # Get stock information and news
    stock_info = get_stock_info(CONFIG['company']['ticker'])
    if stock_info is None:
        print("Failed to get stock information. Email will not be sent.")
        return
    
    news_articles = get_company_news(CONFIG['company'])
    
    # Create and send email
    html_content = create_email_content(CONFIG['company'], stock_info, news_articles)
    send_email(CONFIG['email'], CONFIG['company'], html_content)

if __name__ == "__main__":
    main()