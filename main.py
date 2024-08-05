import re
import os
import base64
import requests
import urllib.parse
from datetime import datetime
from twilio.rest import Client

def identify_provider(tracking_code):
    carriers = {
        "correios": r"^((?!ME)[A-Z]){2}\d{9}[A-Z]{2}$",
        "jadlog": r"^(1008|18\d\d)\d{10}$|^(?!957)\d{9,13}$",
        "buslog": r"(^BUS-[0-9]{8}$)|(^\d{8}$)",
        "azul": r"(^[A-Z]{3}-[A-Z]{2}[0-9]{8}$)|(^9[0-9]{7}$)|(^7[0-9]{1}[0-9]{6}$)|(^577[0-9]{8}$)|(^5[1-9]{1}[0-9]{6}$)|(^800[0-9]{1}[0-9]{7}$)|(^[A-Z]{2}[0-9]{8}$)",
        "latam": r"(^66[0-9]{6,12}$)|(^65[0-9]{6,12}$)|(^95[0-9]{6,12}$)|(^957[0-9]{6,12}$)|(^[LTM-]{4}(66|65|95|957)[0-9]{6,12}$)",
        "melhorenvio": r"^[ME]{2}.{9,}[A-Z]{2}$",
        "loggi": r"^LGI-[A-Z]{2}\w{9}[A-Z]{2}",
        "jet": r"^888[0-9]{12}$"
    }
    
    for carrier, pattern in carriers.items():
        if re.match(pattern, tracking_code):
            return carrier
    
    return None

def make_request(tracking_code, provider_type):
    url = 'https://api.melhorrastreio.com.br/graphql'
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Cache-Control': 'no-cache'
    }
    body = {
        "query": """
        mutation searchParcel ($tracker: TrackerSearchInput!) {
            result: searchParcel (tracker: $tracker) {
                id
                createdAt
                updatedAt
                lastStatus
                lastSyncTracker
                nextSyncTracker
                pudos {
                    type
                    trackingCode
                }
                trackers {
                    type
                    shippingService
                    trackingCode
                }
                trackingEvents {
                    trackerType
                    trackingCode
                    createdAt
                    translatedEventId
                    description
                    title
                    to
                    from
                    location {
                        zipcode
                        address
                        locality
                        number
                        complement
                        city
                        state
                        country
                    }
                    additionalInfo
                }
                pudoEvents {
                    pudoType
                    trackingCode
                    createdAt
                    translatedEventId
                    description
                    title
                    from
                    to
                    location {
                        zipcode
                        address
                        locality
                        number
                        complement
                        city
                        state
                        country
                    }
                    additionalInfo
                }
            }
        }
        """,
        "variables": {
            "tracker": {
                "trackingCode": tracking_code,
                "type": provider_type
            }
        }
    }

    response = requests.post(url, headers=headers, json=body)

    if response.status_code != 200:
        return {
            "message": "Unable to complete the request due to an error from the server."
        }

    return response.json()

def lambda_handler(event, context):
    try:        
        from_, body, to = decode_values(event['body'])
        
        if not body:
            return {
                "message": "Body is required."
            }

        tracking_code = body
        provider = identify_provider(tracking_code)
        
        if not provider:
            return {
                "message": "Provider could not be identified."
            }
        
        response_json = make_request(tracking_code, provider)
        if 'errors' in response_json:
            if isinstance(response_json['errors'], list):
                return response_json
            else:
                return {
                    "message": "Unable to complete the request."
                }
        else:
            handle_message(response_json, to, from_)
            return {
                    "message": "Message sent successfully."
                }
    except Exception as e:
        return {
            "message": f"Error processing request: {str(e)}"
        }

def format_date(date_str):
    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    return dt.strftime("%d/%m/%Y às %H:%M")

def send_message(text, from_, to_):
    account_sid = os.getenv("account_sid")
    auth_token = os.getenv("auth_token")
    client = Client(account_sid, auth_token)

    client.messages.create(
        from_=from_,
        body=f'{text}',
        to=to_
    )

def handle_event_message(tracking_code, shipping_service, last_event):
    message = f"📦 Pacote: *{tracking_code}* \n🚛 Transportadora: *{shipping_service}*"
    message += f"\n📅 Data: {format_date(last_event.get('createdAt'))} \nℹ️ Situação: {last_event.get('title')}"
    
    if last_event.get("from"):
        message += f"\n📦 De: {last_event.get('from')}"
    
    if last_event.get("to"):
        message += f"\n📬 Para: {last_event.get('to')}"
    
    if last_event.get("additionalInfo"):
        message += "\n🔍 Informações adicionais: "
        additional_info = last_event.get('additionalInfo')
        match = re.search(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', additional_info)
        if match:
            url = match.group(1)
            anchor_text = match.group(2)
            
            decoded_url = urllib.parse.unquote(url)
            
            message += additional_info.replace(match.group(0), f'{anchor_text}: {decoded_url}')
        else:
            message += f"{additional_info}"
            
    return message

def handle_message(response, from_, to_):
    result = response["data"]["result"]
    message = '*Não foi possível rastrear pacote!* \nVerifique se o seu código está correto. Caso esteja, tente novamente mais tarde, pois as informações podem demorar algumas horas para serem atualizadas.'

    if result is not None:
        events = result['trackingEvents']
        if events is not None:
            events.sort(key=lambda x: datetime.fromisoformat(x["createdAt"].replace('Z', '+00:00')), reverse=True)
            message = handle_event_message(result['trackers'][0]['trackingCode'], result['trackers'][0]['type'].capitalize(), events[0])       
    send_message(message, from_, to_)

def decode_values(body):
    decoded_bytes = base64.b64decode(body)
    decoded_string = decoded_bytes.decode('utf-8')
    params = urllib.parse.parse_qs(decoded_string)

    params = {key: value[0] for key, value in params.items()}

    from_param = params.get("From")
    body_param = params.get("Body")
    to_param = params.get("To")
    
    return from_param, body_param, to_param