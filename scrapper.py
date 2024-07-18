from itertools import chain
from bs4 import BeautifulSoup
from datetime import datetime
from lxml import etree
import asyncio, aiohttp
import concurrent.futures
import hashlib
import pymongo
import requests, time, random

class TrustPilotScrapper:
    def __init__(self, NUM_PAGES, MAX_PAGES, database_name, collection_name):
        """ Python class to class to make asynchronous calls """
        self.main_page = "https://www.trustpilot.com"
        self.mongo_client = pymongo.MongoClient("mongodb://localhost:27017/")
        self.num_pages = NUM_PAGES   # Number of pages to scrape (choosing how many organizations wil be considered)
        self.max_pages = MAX_PAGES   # Number of pages to be scraped for each organization
        self.database_name = database_name  # MongoDB database name
        self.collection_name = collection_name   # MongoDB collections name, stored within database
        self.MAX_THREADS = 30  # Number of concurrent threads for multithreading
        self.page_urls = []
        self.page_numbers = []

    async def scrape_content_page_urls(self):
        """ Asynchronous function for retrieving page URLs """
        base_url_pages = [f'https://www.trustpilot.com/categories/electronics_technology?page={i}&sort=latest_review' for i in range(1,self.num_pages+1)] # Creating URL list based upon number of pages to consider 
        async with aiohttp.ClientSession() as session:  # Creating a session object for extracting page links for each organization
            page_links = await self.fetch_page_urls(session, base_url_pages)  
            return list(chain.from_iterable(page_links))
        
    
    async def fetch_page_urls(self,session,urls):
        """ Asynchronous function for creating async tasks for extracting page URLs"""
        tasks = []
        for url in urls:
            task = asyncio.create_task(self.fetch_url(session, url))
            tasks.append(task)
        result = await asyncio.gather(*tasks)
        return result
    

    async def fetch_url(self, session, url):
        """ Function to retrieve page link """
        await asyncio.sleep(2)
        async with session.get(url) as response:
            html_content = await response.text()
            list_urls = []
            soup = BeautifulSoup(html_content, 'lxml')
            link_soup = soup.find_all( "div", class_ = "paper_paper__1PY90 paper_outline__lwsUX card_card__lQWDv card_noPadding__D8PcU styles_wrapper__2JOo2")
            for element in link_soup:
                list_urls.append(self.main_page + element.a['href'])
        return list_urls
    

    async def scrap_page_numbers(self):
        """ Asynchronous function for retrieving page numbers """
        page_number_tasks = []
        await asyncio.sleep(2)
        async with aiohttp.ClientSession() as session:
            for url in self.page_urls:
                task = asyncio.create_task(self.fetch_page_number(session, url))
                page_number_tasks.append(task)
            result = await asyncio.gather(*page_number_tasks)
        return result


    async def fetch_page_number(self, session, url):
        """ Function to retrieve page number of the input url """
        async with session.get(url) as response:
            page_number = 0
            page_content = await response.text()
            page_soup = BeautifulSoup(page_content, 'lxml')
            for item in page_soup.select("a"):
                try:
                    if item['name'] == "pagination-button-last":
                        page_number = int(item['aria-label'].strip().split()[-1])
                        break
                except:
                    continue
        return page_number
    

    def scrap_company_reviews(self, base_url, page_limit, mycol):
        """ Function for scraping reviews from input organization & reading results to MongoDB collection"""
        sleep_duration = random.randint(100,250)
        time.sleep(sleep_duration)
        page_reviews = []
        url_list = [base_url + f"?page={i}" for i in range(1,page_limit+1)]
        threads = min(self.MAX_THREADS, len(url_list))
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            page_reviews.append(list(executor.map(self.scrape_page, url_list)))
        reviews = list(chain.from_iterable(page_reviews[0]))
        x = mycol.insert_many(reviews)
        return ''

        
    def scrape_page(self, new_link):
        """ Function for extracting reviews from input link """
        time.sleep(5)
        list_reviews = []
        response = requests.get(new_link)
        if response.status_code!= 200:
            return [{'Error' : f'Could not scrape {new_link}'}]
        content = response.content.decode("utf-8") 
        soup = BeautifulSoup(content, 'lxml') 
        dom =  etree.HTML(str(soup))  
        block_xpath = '/html/body/div[1]/div/div/main/div/div[4]/section/div'
        for i in range(len(dom.xpath(block_xpath))):
            try:
                username = str(dom.xpath(f'/html/body/div[1]/div/div/main/div/div[4]/section/div[{i}]/article/div/aside/div/a/span')[0].text)
            except:
                username = 'NOT FOUND'
            try:
                location = str(dom.xpath(f'/html/body/div[1]/div/div/main/div/div[4]/section/div[{i}]/article/div/aside/div/a/div/div/span')[0].text)
            except:
                location = 'NOT FOUND'
            try:
                review = str(dom.xpath(f'/html/body/div[1]/div/div/main/div/div[4]/section/div[{i}]/article/div/section/div[2]/p[1]')[0].text)
            except:
                review = 'NOT FOUND'
            try:
                rating = str(dom.xpath(f'/html/body/div[1]/div/div/main/div/div[4]/section/div[{i}]/article/div/section/div[1]/div[1]/img')[0].get('alt'))
            except:
                rating = 'NOT FOUND'
            try:
                title = str(dom.xpath(f'/html/body/div[1]/div/div/main/div/div[4]/section/div[{i}]/article/div/section/div[2]/a/h2')[0].text)
            except:
                title = 'NOT FOUND'
            
            temp_param = {
                'Username' : username, 'Location' : location, 
                'Review' : review, 'Rating' : rating, 
                'Title' : title
            }
            list_reviews.append(temp_param)
        return list_reviews

    def scrape_website(self):
        # Extract URLs & page numbers of desired webpages from main content page
        self.page_urls  = asyncio.run(self.scrape_content_page_urls())
        pages = asyncio.run(self.scrap_page_numbers())

        # Clipping page number values to maximum page limit 
        self.page_numbers = [self.max_pages if page == 0 or page > self.max_pages else min(page, self.max_pages) for page in pages]
        
        # Initializing MOngoDB database & collection
        mydb = self.mongo_client[self.database_name]
        mycol = mydb[self.collection_name]

        # Randomly sampling URLs for scrapping 
        final_dict = dict(zip(self.page_urls, self.page_numbers))
        length_dict = len(final_dict)
        while length_dict > 0:
            hash_str = hashlib.md5(str(final_dict).encode('utf-8')).hexdigest() # get the md5 hash of the dictionary as a string
            hash_int = int(hash_str, 16) # convert the hash string to an integer
            random_key = list(final_dict.keys())[hash_int % len(final_dict)] # get the key-value pair based on the hash integer
            random_value = final_dict[random_key]
            self.scrap_company_reviews(random_key, random_value, mycol)
            del final_dict[random_key]
            length_dict-=1
        return 0


# Calculating Time of Execution
start = datetime.now()
scrape_status = TrustPilotScrapper(20,50, database_name = "TrustPilotDatabase", collection_name = "ReviewCollection").scrape_website()
end = datetime.now()
td = (end - start).total_seconds() * 10**3
print(f"The time of execution of above program is : {td:.03f}ms")