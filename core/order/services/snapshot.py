
class SnapshotService:

    @staticmethod
    def user_snapshot(user):

        return {
            "full_name": user.profile.get_fullname(),
            "phone": user.profile.phone_number,
            "email": user.email,
        }

    @staticmethod
    def address_snapshot(address):

        return {
            "address": address.address,
            "city": address.city,
            "state": address.state,
            "zip_code": address.zip_code,
        }

    @staticmethod
    def coupon_snapshot(coupon):

        if coupon is None:
            return {
                "coupon": None,
                "coupon_code": None,
                "coupon_discount_percent": None,
            }

        return {
            "coupon": coupon,
            "coupon_code": coupon.code,
            "coupon_discount_percent": coupon.discount_percent,
        }