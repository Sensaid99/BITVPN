"""Payment processing utilities for VPN Bot"""

import logging
import hashlib
import hmac
import json
import uuid
import base64
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from bot.config.settings import Config

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """Custom payment processing error"""
    pass


class YooMoneyPayment:
    """YooMoney payment processor"""
    
    def __init__(self):
        self.token = Config.YOOMONEY_TOKEN
        self.base_url = "https://yoomoney.ru/api"
    
    def create_payment(self, amount: int, order_id: str, description: str) -> Dict[str, Any]:
        """Create YooMoney payment"""
        try:
            url = f"{self.base_url}/request-payment"
            data = {
                'pattern_id': 'p2p',
                'to': self.token,
                'amount': amount / 100,  # Convert kopecks to rubles
                'comment': description,
                'message': description,
                'label': order_id
            }
            
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            response = requests.post(url, data=data, headers=headers, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('status') == 'success':
                return {
                    'payment_id': result.get('request_id'),
                    'payment_url': f"https://yoomoney.ru/checkout/payments/v2/contract?request_id={result.get('request_id')}",
                    'amount': amount,
                    'expires_at': datetime.utcnow() + timedelta(minutes=15)
                }
            else:
                raise PaymentError(f"YooMoney error: {result.get('error')}")
                
        except requests.RequestException as e:
            logger.error(f"YooMoney API error: {e}")
            raise PaymentError("Ошибка подключения к YooMoney")
        except Exception as e:
            logger.error(f"YooMoney payment creation error: {e}")
            raise PaymentError("Ошибка создания платежа YooMoney")
    
    def check_payment(self, payment_id: str) -> str:
        """Check YooMoney payment status"""
        try:
            url = f"{self.base_url}/operation-details"
            data = {'operation_id': payment_id}
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            response = requests.post(url, data=data, headers=headers, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            status = result.get('status', 'unknown')
            
            if status == 'success':
                return 'completed'
            elif status in ['refused', 'failed']:
                return 'failed'
            else:
                return 'pending'
                
        except Exception as e:
            logger.error(f"YooMoney payment check error: {e}")
            return 'unknown'


class YooKassaPayment:
    """ЮKassa (YooKassa) payment processor — API v3"""

    def __init__(self):
        self.shop_id = Config.YOOKASSA_SHOP_ID
        self.secret_key = Config.YOOKASSA_SECRET_KEY
        self.base_url = "https://api.yookassa.ru/v3"

    def _auth_header(self) -> str:
        raw = f"{self.shop_id}:{self.secret_key}"
        return "Basic " + base64.b64encode(raw.encode()).decode()

    def create_payment(self, amount: int, order_id: str, description: str, payment_method_type: str | None = None) -> Dict[str, Any]:
        """Create ЮKassa payment. amount — в копейках. payment_method_type: None = форма выбора, 'sbp' = только СБП."""
        try:
            url = f"{self.base_url}/payments"
            value_rub = f"{(amount / 100):.2f}"
            # СБП отображается в форме только при одностадийной оплате (capture=true)
            payload = {
                "amount": {"value": value_rub, "currency": "RUB"},
                "capture": True,
                "confirmation": {
                    "type": "redirect",
                    "return_url": "https://t.me/",  # пользователь вернётся в Telegram
                },
                "description": description[:255],
                "metadata": {"order_id": order_id},
            }
            if payment_method_type == "sbp":
                payload["payment_method_data"] = {"type": "sbp"}
            headers = {
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Idempotence-Key": str(uuid.uuid4()),
            }
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if not response.ok:
                try:
                    err = response.json()
                    msg = err.get("description") or err.get("message") or response.text[:200]
                except Exception:
                    msg = response.text[:200] if response.text else "HTTP %s" % response.status_code
                logger.error("YooKassa API error: %s %s", response.status_code, msg)
                raise PaymentError(msg or "Ошибка ЮKassa")
            result = response.json()
            conf = result.get("confirmation", {})
            payment_url = conf.get("confirmation_url", "")
            if not payment_url:
                raise PaymentError("ЮKassa не вернула ссылку на оплату")
            return {
                "payment_id": result["id"],
                "payment_url": payment_url,
                "amount": amount,
                "expires_at": datetime.utcnow() + timedelta(minutes=30),
            }
        except PaymentError:
            raise
        except requests.RequestException as e:
            logger.error(f"YooKassa API error: {e}")
            raise PaymentError("Ошибка подключения к ЮKassa")
        except Exception as e:
            logger.error(f"YooKassa payment creation error: {e}")
            raise PaymentError("Ошибка создания платежа ЮKassa")

    def check_payment(self, payment_id: str) -> str:
        """Check ЮKassa payment status."""
        try:
            url = f"{self.base_url}/payments/{payment_id}"
            headers = {
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            status = result.get("status", "").lower()
            if status == "succeeded":
                return "completed"
            if status in ("canceled", "cancelled"):
                return "failed"
            return "pending"
        except Exception as e:
            logger.error(f"YooKassa payment check error: {e}")
            return "unknown"


class QiwiPayment:
    """QIWI payment processor"""
    
    def __init__(self):
        self.token = Config.QIWI_TOKEN
        self.base_url = "https://api.qiwi.com"
    
    def create_payment(self, amount: int, order_id: str, description: str) -> Dict[str, Any]:
        """Create QIWI payment"""
        try:
            url = f"{self.base_url}/partner/bill/v1/bills/{order_id}"
            
            data = {
                'amount': {
                    'currency': 'RUB',
                    'value': f"{amount / 100:.2f}"
                },
                'comment': description,
                'expirationDateTime': (datetime.utcnow() + timedelta(minutes=15)).isoformat() + 'Z',
                'customer': {},
                'customFields': {}
            }
            
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            response = requests.put(url, json=data, headers=headers, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            return {
                'payment_id': result['billId'],
                'payment_url': result['payUrl'],
                'amount': amount,
                'expires_at': datetime.utcnow() + timedelta(minutes=15)
            }
            
        except requests.RequestException as e:
            logger.error(f"QIWI API error: {e}")
            raise PaymentError("Ошибка подключения к QIWI")
        except Exception as e:
            logger.error(f"QIWI payment creation error: {e}")
            raise PaymentError("Ошибка создания платежа QIWI")
    
    def check_payment(self, payment_id: str) -> str:
        """Check QIWI payment status"""
        try:
            url = f"{self.base_url}/partner/bill/v1/bills/{payment_id}"
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            status = result.get('status', {}).get('value', 'unknown')
            
            if status == 'PAID':
                return 'completed'
            elif status in ['REJECTED', 'EXPIRED']:
                return 'failed'
            else:
                return 'pending'
                
        except Exception as e:
            logger.error(f"QIWI payment check error: {e}")
            return 'unknown'


class CryptomusPayment:
    """Cryptomus cryptocurrency payment processor"""
    
    def __init__(self):
        self.api_key = Config.CRYPTOMUS_API_KEY
        self.merchant_id = Config.CRYPTOMUS_MERCHANT_ID
        self.base_url = "https://api.cryptomus.com/v1"
    
    def _generate_signature(self, data: dict) -> str:
        """Generate signature for Cryptomus API"""
        json_data = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        encoded_data = json_data.encode('utf-8')
        signature = hmac.new(
            self.api_key.encode('utf-8'),
            encoded_data,
            hashlib.md5
        ).hexdigest()
        return signature
    
    def create_payment(self, amount: int, order_id: str, description: str) -> Dict[str, Any]:
        """Create cryptocurrency payment"""
        try:
            url = f"{self.base_url}/payment"
            
            data = {
                'amount': str(amount / 100),  # Convert to rubles
                'currency': 'RUB',
                'order_id': order_id,
                'merchant': self.merchant_id,
                'url_callback': 'https://your-domain.com/webhook/cryptomus',
                'url_return': 'https://t.me/your_bot',
                'url_success': 'https://t.me/your_bot',
                'is_payment_multiple': False,
                'lifetime': 900,  # 15 minutes
                'to_currency': 'USDT'  # Default to USDT
            }
            
            headers = {
                'merchant': self.merchant_id,
                'sign': self._generate_signature(data),
                'Content-Type': 'application/json'
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('state') == 0:  # Success
                payment_data = result.get('result', {})
                return {
                    'payment_id': payment_data.get('uuid'),
                    'payment_url': payment_data.get('url'),
                    'amount': amount,
                    'expires_at': datetime.utcnow() + timedelta(minutes=15)
                }
            else:
                raise PaymentError(f"Cryptomus error: {result.get('message')}")
                
        except requests.RequestException as e:
            logger.error(f"Cryptomus API error: {e}")
            raise PaymentError("Ошибка подключения к Cryptomus")
        except Exception as e:
            logger.error(f"Cryptomus payment creation error: {e}")
            raise PaymentError("Ошибка создания криптоплатежа")
    
    def check_payment(self, payment_id: str) -> str:
        """Check cryptocurrency payment status"""
        try:
            url = f"{self.base_url}/payment/info"
            data = {
                'merchant': self.merchant_id,
                'uuid': payment_id
            }
            
            headers = {
                'merchant': self.merchant_id,
                'sign': self._generate_signature(data),
                'Content-Type': 'application/json'
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('state') == 0:
                payment_data = result.get('result', {})
                status = payment_data.get('payment_status')
                
                if status == 'paid':
                    return 'completed'
                elif status in ['fail', 'cancel', 'system_fail']:
                    return 'failed'
                else:
                    return 'pending'
            
            return 'unknown'
            
        except Exception as e:
            logger.error(f"Cryptomus payment check error: {e}")
            return 'unknown'


class PaymentManager:
    """Main payment manager class"""
    
    def __init__(self):
        self.yoomoney = YooMoneyPayment() if Config.YOOMONEY_TOKEN else None
        self.yookassa = YooKassaPayment() if (Config.YOOKASSA_SHOP_ID and Config.YOOKASSA_SECRET_KEY) else None
        self.qiwi = QiwiPayment() if Config.QIWI_TOKEN else None
        self.cryptomus = CryptomusPayment() if Config.CRYPTOMUS_API_KEY else None

    def create_payment(self, method: str, amount: int, order_id: str, description: str) -> Dict[str, Any]:
        """Create payment with specified method"""
        try:
            if method == 'yoomoney' and self.yoomoney:
                return self.yoomoney.create_payment(amount, order_id, description)
            elif method == 'yookassa' and self.yookassa:
                return self.yookassa.create_payment(amount, order_id, description)
            elif method == 'sbp' and self.yookassa:
                return self.yookassa.create_payment(amount, order_id, description, payment_method_type="sbp")
            elif method == 'qiwi' and self.qiwi:
                return self.qiwi.create_payment(amount, order_id, description)
            elif method == 'crypto' and self.cryptomus:
                return self.cryptomus.create_payment(amount, order_id, description)
            else:
                raise PaymentError(f"Платежный метод {method} недоступен")
                
        except PaymentError:
            raise
        except Exception as e:
            logger.error(f"Payment creation error: {e}")
            raise PaymentError("Ошибка создания платежа")
    
    def check_payment(self, method: str, payment_id: str) -> str:
        """Check payment status"""
        try:
            if method == 'yoomoney' and self.yoomoney:
                return self.yoomoney.check_payment(payment_id)
            elif method == 'yookassa' and self.yookassa:
                return self.yookassa.check_payment(payment_id)
            elif method == 'sbp' and self.yookassa:
                return self.yookassa.check_payment(payment_id)
            elif method == 'qiwi' and self.qiwi:
                return self.qiwi.check_payment(payment_id)
            elif method == 'crypto' and self.cryptomus:
                return self.cryptomus.check_payment(payment_id)
            else:
                return 'unknown'
                
        except Exception as e:
            logger.error(f"Payment check error: {e}")
            return 'unknown'
    
    def get_available_methods(self) -> list:
        """Get list of available payment methods"""
        methods = []
        if self.yoomoney:
            methods.append('yoomoney')
        if self.yookassa:
            methods.append('sbp')   # СБП через ЮKassa — первым
            methods.append('yookassa')  # Банковская карта — вторым
        if self.qiwi:
            methods.append('qiwi')
        if self.cryptomus:
            methods.append('crypto')
        return methods


# Global payment manager instance
payment_manager = PaymentManager()