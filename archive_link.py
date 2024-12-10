from atproto import Client
from atproto import models
import requests
from requests.adapters import HTTPAdapter, Retry
import json
import itertools
import tracemalloc
import os
from time import sleep


ARCHIVE_AVAILABILITY_URL='https://archive.org/wayback/available?url='
ARCHIVE_SAVE_URL='https://web.archive.org/save/'
MAX_NUMBER_PER_BATCH = 1000
FETCH_SLEEP_SECONDS = 10


def post_reply_for_mention(mention):
    parent_uri = mention.record.reply.parent.uri
    parent = client.get_posts([parent_uri])

    link_to_archive = parent.posts[0].embed.external.uri
    link_title = parent.posts[0].embed.external.title
    link_description = parent.posts[0].embed.external.description

    reply_to = models.AppBskyFeedPost.ReplyRef(
                parent=models.ComAtprotoRepoStrongRef.Main(
                    cid=mention.cid,
                    uri=mention.uri
                ),
                root=models.ComAtprotoRepoStrongRef.Main(
                    cid=mention.record.reply.root.cid,
                    uri=mention.record.reply.root.uri
                )
            )

    cached_url = check_if_already_available(link_to_archive)

    if cached_url is None:
        cached_url = get_request(ARCHIVE_SAVE_URL, link_to_archive).url

    if cached_url:
        post_archived_url_as_reply({'url': cached_url, 'title': link_title, 'description': link_description}, reply_to)
    else:
        post_failure_as_reply()
        

def check_if_already_available(url):
    availability_response = requests.get(ARCHIVE_AVAILABILITY_URL + url)
    response_json = json.loads(availability_response.content)
    if response_json['archived_snapshots']:
        return response_json['archived_snapshots']['closest']['url']
    else:
        return None    


def post_archived_url_as_reply(url_dict, reply_to):
    client.send_post(
        text="Here's an archived link for this URL",
        embed=models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
            description=url_dict['description'],
            title=url_dict['title'],
            uri=url_dict['url']
        )),
        reply_to=reply_to
    )


def post_failure_as_reply():
    return None


def get_request(base_url, url_suffix):
    session = requests.Session()
    
    retry_strategy = Retry(total = 3,
                           backoff_factor=0.1,
                           status_forcelist=[500, 502, 503, 504]) 
    
    http_adapter = HTTPAdapter(max_retries=retry_strategy)
    
    session.mount('http://', http_adapter)
    session.mount('https://', http_adapter)
    
    try:
        response = session.get(base_url + url_suffix)
    except requests.exceptions.RequestException as ex:
        raise RuntimeError('Unable to request URL', ex)
    
    return response


tracemalloc.start()

client = Client()
client.login(os.environ.get('ARCHIVE_BOT_HANDLE'), os.environ.get('ARCHIVE_BOT_PASSWORD'))

while True:
    response = client.app.bsky.notification.list_notifications()
    last_seen_time = client.get_current_time_iso()
    unread_mentions = [notification for notification in response.notifications 
                    if notification.reason == 'mention' and notification.is_read == False]

    print('Found {0} unread mentions to process, out of {1} total notifications retrieved.'.format(len(unread_mentions), len(response.notifications)))

    for mention in itertools.islice(unread_mentions, MAX_NUMBER_PER_BATCH):
        post_reply_for_mention(mention)
        
        
    print('Updating notification last_seen time with {0}'.format(last_seen_time))
    client.app.bsky.notification.update_seen({
        'seen_at': last_seen_time
    })
        
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    print('Current memory usage: {0} KiB \nPeak memory usage: {1} KiB'.format(int(current_mem / 1024), int(peak_mem / 1024)))
    tracemalloc.stop()
    
    sleep(FETCH_SLEEP_SECONDS)
