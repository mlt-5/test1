#!/usr/bin/env python3
"""
Nifty 50 Options Chain Extractor using Kite Connect API

This script fetches Nifty options chain data for:
- Nearest weekly expiry (ATM ±10 strikes)
- Current month expiry (ATM ±10 strikes)

Exports to separate CSV files.
"""

import os
import sys
import json
import webbrowser
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import pandas as pd

# Suppress urllib3 OpenSSL warning (cosmetic issue, doesn't affect functionality)
import warnings
warnings.filterwarnings('ignore', message='.*OpenSSL.*')

from kiteconnect import KiteConnect
import greeks_calculator

# Import configuration
try:
    import kite_config as config
except ImportError:
    print("Error: kite_config.py not found or not configured properly")
    print("Please ensure kite_config.py exists with your API credentials")
    sys.exit(1)


class NiftyOptionsChain:
    def __init__(self):
        """Initialize Kite Connect API client"""
        self.api_key = config.API_KEY
        self.api_secret = config.API_SECRET
        self.redirect_url = config.REDIRECT_URL
        self.access_token_file = config.ACCESS_TOKEN_FILE

        # Validate credentials
        if self.api_key == "your_api_key_here" or self.api_secret == "your_api_secret_here":
            print("Error: Please configure your API credentials in kite_config.py")
            print("Visit https://developers.kite.trade/ to get your credentials")
            sys.exit(1)

        self.kite = KiteConnect(api_key=self.api_key)
        self.access_token = None
        self.nfo_instruments = None  # Cache for NFO instruments

    def authenticate(self):
        """Handle Kite Connect authentication"""
        # Try to load existing access token
        if os.path.exists(self.access_token_file):
            try:
                with open(self.access_token_file, 'r') as f:
                    token_data = json.load(f)
                    saved_date = token_data.get('date')
                    today = datetime.now().strftime('%Y-%m-%d')

                    # Check if token is from today (tokens expire at 6 AM next day)
                    if saved_date == today:
                        self.access_token = token_data.get('access_token')
                        self.kite.set_access_token(self.access_token)
                        print("✓ Using saved access token")
                        return True
            except Exception as e:
                print(f"Warning: Could not load saved token: {e}")

        # Need to generate new access token
        print("\n" + "="*60)
        print("Authentication Required")
        print("="*60)

        # Generate login URL
        login_url = self.kite.login_url()
        print(f"\nOpening browser for login...")
        print(f"If browser doesn't open, visit this URL:\n{login_url}\n")

        # Open browser
        webbrowser.open(login_url)

        # Get request token from user
        print("After logging in, you'll be redirected to your redirect URL.")
        print("Copy the FULL URL from your browser and paste it here.\n")
        redirect_response = input("Enter the redirect URL: ").strip()

        try:
            # Parse request token from URL
            parsed_url = urlparse(redirect_response)
            request_token = parse_qs(parsed_url.query).get('request_token', [None])[0]

            if not request_token:
                print("Error: Could not find request_token in URL")
                return False

            # Generate session
            data = self.kite.generate_session(request_token, api_secret=self.api_secret)
            self.access_token = data["access_token"]
            self.kite.set_access_token(self.access_token)

            # Save access token
            token_data = {
                'access_token': self.access_token,
                'date': datetime.now().strftime('%Y-%m-%d')
            }
            with open(self.access_token_file, 'w') as f:
                json.dump(token_data, f)

            print("✓ Authentication successful!")
            return True

        except Exception as e:
            print(f"✗ Authentication failed: {e}")
            return False

    def get_nifty_spot_price(self):
        """Get current Nifty 50 spot price"""
        try:
            # Try to get Nifty 50 from NSE
            quote = self.kite.quote("NSE:NIFTY 50")
            if quote and "NSE:NIFTY 50" in quote:
                ltp = quote["NSE:NIFTY 50"]["last_price"]
                print(f"✓ Nifty 50 spot price: {ltp}")
                return ltp
        except:
            pass

        try:
            # Fallback: Try indices
            quote = self.kite.quote("NSE:NIFTY50")
            if quote and "NSE:NIFTY50" in quote:
                ltp = quote["NSE:NIFTY50"]["last_price"]
                print(f"✓ Nifty 50 spot price: {ltp}")
                return ltp
        except:
            pass

        print("✗ Could not fetch Nifty spot price")
        return None

    def get_nifty_futures_price(self, expiry_date):
        """Get Nifty futures price for nearest expiry"""
        try:
            # Use cached instruments if available
            if self.nfo_instruments is None:
                print("⚠ NFO instruments not cached, fetching...")
                self.nfo_instruments = self.kite.instruments("NFO")

            # Filter for Nifty futures matching the expiry
            nifty_futures = [
                inst for inst in self.nfo_instruments
                if inst['name'] == 'NIFTY' and
                   inst['instrument_type'] == 'FUT' and
                   inst['expiry'] == expiry_date
            ]

            print(f"Debug: Found {len(nifty_futures)} Nifty futures for expiry {expiry_date}")

            if nifty_futures:
                # Get the first matching futures contract
                fut_symbol = nifty_futures[0]['tradingsymbol']
                fut_key = f"NFO:{fut_symbol}"

                # Fetch quote
                quote = self.kite.quote(fut_key)
                if quote and fut_key in quote:
                    ltp = quote[fut_key]["last_price"]
                    print(f"✓ Nifty Futures ({fut_symbol}): {ltp}")
                    return ltp
                else:
                    print(f"⚠ Quote not found for {fut_key}")
            else:
                print(f"⚠ No Nifty futures found for expiry {expiry_date}")
                # Debug: Show available futures
                all_nifty_fut = [inst for inst in self.nfo_instruments
                                if inst['name'] == 'NIFTY' and inst['instrument_type'] == 'FUT']
                print(f"Debug: Available Nifty futures expiries: {[inst['expiry'] for inst in all_nifty_fut[:5]]}")

        except Exception as e:
            print(f"✗ Error fetching futures price: {e}")
            import traceback
            traceback.print_exc()

        return None

    def get_atm_strike(self, spot_price, strike_gap=50):
        """Calculate ATM strike price"""
        return round(spot_price / strike_gap) * strike_gap

    def get_strike_range(self, atm_strike, num_strikes=10, strike_gap=50):
        """Get strike range: ATM ±num_strikes"""
        strikes = []
        for i in range(-num_strikes, num_strikes + 1):
            strikes.append(atm_strike + (i * strike_gap))
        return strikes

    def fetch_nifty_options(self):
        """Fetch all Nifty options instruments"""
        print("\nFetching Nifty options instruments...")
        try:
            # Cache NFO instruments for reuse (futures, options, etc.)
            if self.nfo_instruments is None:
                self.nfo_instruments = self.kite.instruments("NFO")
                print(f"✓ Cached {len(self.nfo_instruments)} NFO instruments")

            # Filter for Nifty options (CE and PE)
            nifty_options = [
                inst for inst in self.nfo_instruments
                if inst['name'] == 'NIFTY' and inst['instrument_type'] in ['CE', 'PE']
            ]

            print(f"✓ Found {len(nifty_options)} Nifty options")
            return nifty_options

        except Exception as e:
            print(f"✗ Error fetching instruments: {e}")
            return []

    def identify_expiries(self, instruments):
        """
        Identify all future expiries based on smart month filtering logic:
        - If today < current monthly expiry: fetch ONLY current month
        - If today == current monthly expiry: fetch current + next month
        - If today > current monthly expiry: fetch ONLY next month
        """
        from datetime import date as dt_date

        # Get unique expiry dates
        expiry_dates = sorted(set(inst['expiry'] for inst in instruments))

        if not expiry_dates:
            print("✗ No expiry dates found")
            return {'weekly': [], 'monthly': []}

        # Get current date
        today = dt_date.today()
        current_month = today.month
        current_year = today.year

        # Calculate next month
        next_month = (current_month % 12) + 1
        next_year = current_year if current_month < 12 else current_year + 1

        print(f"\nAll available expiry dates: {[exp.strftime('%d-%b-%Y') for exp in expiry_dates[:15]]}")

        # Filter: Only future expiries (>= today)
        future_expiries = [exp for exp in expiry_dates if exp >= today]

        if not future_expiries:
            print("✗ No future expiries found")
            return {'weekly': [], 'monthly': []}

        print(f"Future expiries (>= today): {[exp.strftime('%d-%b-%Y') for exp in future_expiries[:10]]}")

        # Find current month's monthly expiry (last expiry in current month)
        current_month_expiries = [
            exp for exp in expiry_dates
            if exp.month == current_month and exp.year == current_year
        ]

        current_monthly_expiry = current_month_expiries[-1] if current_month_expiries else None

        # Determine which months to fetch based on logic
        months_to_fetch = []

        if current_monthly_expiry:
            print(f"\nCurrent month's expiry: {current_monthly_expiry.strftime('%d-%b-%Y')}")
            print(f"Today's date: {today.strftime('%d-%b-%Y')}")

            if today < current_monthly_expiry.date() if hasattr(current_monthly_expiry, 'date') else current_monthly_expiry:
                # Before monthly expiry: fetch ONLY current month
                months_to_fetch = [(current_year, current_month)]
                print(f"📅 Fetching: CURRENT MONTH only ({today.strftime('%B %Y')})")

            elif today == (current_monthly_expiry.date() if hasattr(current_monthly_expiry, 'date') else current_monthly_expiry):
                # On monthly expiry day: fetch current + next month
                months_to_fetch = [(current_year, current_month), (next_year, next_month)]
                print(f"📅 Fetching: CURRENT + NEXT MONTH ({today.strftime('%B %Y')} + {datetime(next_year, next_month, 1).strftime('%B %Y')})")

            else:
                # After monthly expiry: fetch ONLY next month
                months_to_fetch = [(next_year, next_month)]
                print(f"📅 Fetching: NEXT MONTH only ({datetime(next_year, next_month, 1).strftime('%B %Y')})")
        else:
            # No current month expiries found, default to next month
            months_to_fetch = [(next_year, next_month)]
            print(f"⚠ No current month expiry found")
            print(f"📅 Fetching: NEXT MONTH only ({datetime(next_year, next_month, 1).strftime('%B %Y')})")

        # Filter expiries for selected months
        target_expiries = [
            exp for exp in future_expiries
            if (exp.year, exp.month) in months_to_fetch
        ]

        if not target_expiries:
            print("✗ No expiries found in target months")
            return {'weekly': [], 'monthly': []}

        print(f"\nExpiries to fetch: {[exp.strftime('%d-%b-%Y') for exp in target_expiries]}")

        # Separate into weekly and monthly
        # Monthly expiries are typically the last Thursday of each month
        weekly_expiries = []
        monthly_expiries = []

        # Group by month
        months_seen = {}
        for exp in target_expiries:
            month_key = (exp.year, exp.month)
            if month_key not in months_seen:
                months_seen[month_key] = []
            months_seen[month_key].append(exp)

        # For each month, the last expiry is monthly, others are weekly
        for month_key, month_expiries in months_seen.items():
            month_expiries.sort()
            if len(month_expiries) > 1:
                # All but last are weekly
                weekly_expiries.extend(month_expiries[:-1])
                # Last one is monthly
                monthly_expiries.append(month_expiries[-1])
            else:
                # Only one expiry in the month - classify as monthly
                monthly_expiries.append(month_expiries[0])

        # Sort for consistent ordering
        weekly_expiries.sort()
        monthly_expiries.sort()

        print(f"\n✓ Found {len(weekly_expiries)} weekly expiries:")
        for exp in weekly_expiries:
            print(f"    - {exp.strftime('%d-%b-%Y (%A)')}")

        print(f"✓ Found {len(monthly_expiries)} monthly expiries:")
        for exp in monthly_expiries:
            print(f"    - {exp.strftime('%d-%b-%Y (%A)')}")

        return {'weekly': weekly_expiries, 'monthly': monthly_expiries}

    def filter_options_by_expiry_and_strikes(self, instruments, expiry, strikes):
        """Filter options for specific expiry and strike range"""
        filtered = []

        for inst in instruments:
            if inst['expiry'] == expiry and inst['strike'] in strikes:
                filtered.append(inst)

        return filtered

    def fetch_market_data(self, instruments):
        """Fetch market data for given instruments"""
        print(f"\nFetching market data for {len(instruments)} instruments...")

        # Prepare instrument keys
        instrument_keys = [f"NFO:{inst['tradingsymbol']}" for inst in instruments]

        # Kite allows max 500 instruments per quote request
        # Split into batches if needed
        batch_size = 500
        all_quotes = {}

        for i in range(0, len(instrument_keys), batch_size):
            batch = instrument_keys[i:i+batch_size]
            try:
                quotes = self.kite.quote(batch)
                all_quotes.update(quotes)
            except Exception as e:
                print(f"✗ Error fetching quotes for batch: {e}")

        print(f"✓ Fetched market data for {len(all_quotes)} instruments")
        return all_quotes

    def build_options_chain(self, instruments, quotes, strikes, spot_price, expiry_date, futures_price=None):
        """Build options chain dataframe with Greeks calculation"""
        print("✓ Calculating Implied Volatility from market prices using Newton-Raphson method...")
        data = []

        # Calculate time to expiry
        time_to_expiry = greeks_calculator.get_time_to_expiry(expiry_date)

        # Capture timestamp when data is being processed
        capture_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for strike in strikes:
            # Add critical metadata fields first
            row = {
                'Timestamp': capture_timestamp,
                'Underlying_Spot': spot_price,
                'Futures_Price': futures_price if futures_price else 0,
                'Strike_Price': strike
            }

            # Find CE and PE for this strike
            ce_inst = next((inst for inst in instruments
                           if inst['strike'] == strike and inst['instrument_type'] == 'CE'), None)
            pe_inst = next((inst for inst in instruments
                           if inst['strike'] == strike and inst['instrument_type'] == 'PE'), None)

            # Get expiry date
            if ce_inst:
                row['Expiry_Date'] = ce_inst['expiry'].strftime('%d-%b-%Y')
            elif pe_inst:
                row['Expiry_Date'] = pe_inst['expiry'].strftime('%d-%b-%Y')

            # CE (Call) data
            if ce_inst:
                ce_key = f"NFO:{ce_inst['tradingsymbol']}"
                ce_quote = quotes.get(ce_key, {})

                row['CE_OI'] = ce_quote.get('oi', 0)
                row['CE_Change_in_OI'] = ce_quote.get('oi_day_high', 0) - ce_quote.get('oi_day_low', 0)
                row['CE_Volume'] = ce_quote.get('volume', 0)
                row['CE_LTP'] = ce_quote.get('last_price', 0)
                row['CE_Change'] = ce_quote.get('change', 0)

                # Calculate Implied Volatility from market price
                ce_ltp = row['CE_LTP']
                if ce_ltp > 0 and time_to_expiry > 0:
                    ce_iv = greeks_calculator.calculate_implied_volatility(
                        market_price=ce_ltp,
                        spot=spot_price,
                        strike=strike,
                        time_to_expiry=time_to_expiry,
                        option_type='CE'
                    )
                    row['CE_IV'] = round(ce_iv * 100, 2)  # Convert to percentage
                else:
                    ce_iv = 0.15  # Default 15% for Greeks calculation
                    row['CE_IV'] = 0

                # Bid/Ask data
                depth = ce_quote.get('depth', {})
                buy = depth.get('buy', [{}])[0] if depth.get('buy') else {}
                sell = depth.get('sell', [{}])[0] if depth.get('sell') else {}

                row['CE_Bid_Qty'] = buy.get('quantity', 0)
                row['CE_Bid_Price'] = buy.get('price', 0)
                row['CE_Ask_Price'] = sell.get('price', 0)
                row['CE_Ask_Qty'] = sell.get('quantity', 0)

                # Calculate Greeks for CE using the calculated IV
                ce_greeks = greeks_calculator.calculate_all_greeks(
                    spot=spot_price,
                    strike=strike,
                    time_to_expiry=time_to_expiry,
                    volatility=ce_iv,  # Use the IV calculated from market price
                    option_type='CE'
                )
                row['CE_Delta'] = ce_greeks['delta']
                row['CE_Gamma'] = ce_greeks['gamma']
                row['CE_Vega'] = ce_greeks['vega']
                row['CE_Theta'] = ce_greeks['theta']
            else:
                row.update({
                    'CE_OI': 0, 'CE_Change_in_OI': 0, 'CE_Volume': 0, 'CE_IV': 0,
                    'CE_LTP': 0, 'CE_Change': 0, 'CE_Bid_Qty': 0, 'CE_Bid_Price': 0,
                    'CE_Ask_Price': 0, 'CE_Ask_Qty': 0,
                    'CE_Delta': 0, 'CE_Gamma': 0, 'CE_Vega': 0, 'CE_Theta': 0
                })

            # PE (Put) data
            if pe_inst:
                pe_key = f"NFO:{pe_inst['tradingsymbol']}"
                pe_quote = quotes.get(pe_key, {})

                row['PE_Change'] = pe_quote.get('change', 0)
                row['PE_LTP'] = pe_quote.get('last_price', 0)
                row['PE_Volume'] = pe_quote.get('volume', 0)
                row['PE_Change_in_OI'] = pe_quote.get('oi_day_high', 0) - pe_quote.get('oi_day_low', 0)
                row['PE_OI'] = pe_quote.get('oi', 0)

                # Calculate Implied Volatility from market price
                pe_ltp = row['PE_LTP']
                if pe_ltp > 0 and time_to_expiry > 0:
                    pe_iv = greeks_calculator.calculate_implied_volatility(
                        market_price=pe_ltp,
                        spot=spot_price,
                        strike=strike,
                        time_to_expiry=time_to_expiry,
                        option_type='PE'
                    )
                    row['PE_IV'] = round(pe_iv * 100, 2)  # Convert to percentage
                else:
                    pe_iv = 0.15  # Default 15% for Greeks calculation
                    row['PE_IV'] = 0

                # Bid/Ask data
                depth = pe_quote.get('depth', {})
                buy = depth.get('buy', [{}])[0] if depth.get('buy') else {}
                sell = depth.get('sell', [{}])[0] if depth.get('sell') else {}

                row['PE_Bid_Qty'] = buy.get('quantity', 0)
                row['PE_Bid_Price'] = buy.get('price', 0)
                row['PE_Ask_Price'] = sell.get('price', 0)
                row['PE_Ask_Qty'] = sell.get('quantity', 0)

                # Calculate Greeks for PE using the calculated IV
                pe_greeks = greeks_calculator.calculate_all_greeks(
                    spot=spot_price,
                    strike=strike,
                    time_to_expiry=time_to_expiry,
                    volatility=pe_iv,  # Use the IV calculated from market price
                    option_type='PE'
                )
                row['PE_Delta'] = pe_greeks['delta']
                row['PE_Gamma'] = pe_greeks['gamma']
                row['PE_Vega'] = pe_greeks['vega']
                row['PE_Theta'] = pe_greeks['theta']
            else:
                row.update({
                    'PE_Bid_Qty': 0, 'PE_Bid_Price': 0, 'PE_Ask_Price': 0, 'PE_Ask_Qty': 0,
                    'PE_Change': 0, 'PE_LTP': 0, 'PE_IV': 0, 'PE_Volume': 0,
                    'PE_Change_in_OI': 0, 'PE_OI': 0,
                    'PE_Delta': 0, 'PE_Gamma': 0, 'PE_Vega': 0, 'PE_Theta': 0
                })

            data.append(row)

        return pd.DataFrame(data)

    def export_to_csv(self, df, expiry_date, expiry_type):
        """Export dataframe to CSV file in today's date folder"""
        # Create folder with today's date
        today_folder = datetime.now().strftime("%Y-%m-%d")
        os.makedirs(today_folder, exist_ok=True)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        expiry_str = expiry_date.strftime("%d%b%Y")
        filename = f"nifty_{expiry_type}_{expiry_str}_{timestamp}.csv"

        # Full path with date folder
        filepath = os.path.join(today_folder, filename)

        df.to_csv(filepath, index=False)
        print(f"✓ Exported: {filepath}")
        return filepath

    def run(self):
        """Main execution method"""
        import time

        print("="*80)
        print("Nifty 50 Options Chain Extractor (Kite API)")
        print("="*80)

        # Step 1: Authenticate
        if not self.authenticate():
            return

        # Step 2: Get Nifty spot price
        spot_price = self.get_nifty_spot_price()
        if not spot_price:
            print("✗ Cannot proceed without spot price")
            return

        # Step 3: Calculate ATM and strike range
        atm_strike = self.get_atm_strike(spot_price)
        print(f"✓ ATM Strike: {atm_strike}")

        strikes = self.get_strike_range(atm_strike, num_strikes=10)
        print(f"✓ Strike range: {strikes[0]} to {strikes[-1]}")

        # Step 4: Fetch Nifty options
        all_options = self.fetch_nifty_options()
        if not all_options:
            return

        # Step 5: Identify all expiries in current + next month
        expiries_dict = self.identify_expiries(all_options)
        weekly_expiries = expiries_dict['weekly']
        monthly_expiries = expiries_dict['monthly']

        if not weekly_expiries and not monthly_expiries:
            print("✗ No expiries found")
            return

        # Calculate total expiries to process
        total_expiries = len(weekly_expiries) + len(monthly_expiries)
        print(f"\n{'='*80}")
        print(f"TOTAL EXPIRIES TO PROCESS: {total_expiries}")
        print(f"  - Weekly: {len(weekly_expiries)}")
        print(f"  - Monthly: {len(monthly_expiries)}")
        print(f"{'='*80}")

        # Track created files
        created_files = []
        success_count = 0
        error_count = 0
        current_idx = 0

        # Get futures price (use first monthly expiry if available, else first weekly)
        futures_expiry = monthly_expiries[0] if monthly_expiries else weekly_expiries[0] if weekly_expiries else None
        futures_price = None
        if futures_expiry:
            print("\n" + "-"*80)
            print("Fetching Futures Price")
            print("-"*80)
            print(f"Using expiry: {futures_expiry.strftime('%d-%b-%Y')}")
            futures_price = self.get_nifty_futures_price(futures_expiry)

        # Process all weekly expiries
        for expiry in weekly_expiries:
            current_idx += 1
            print("\n" + "="*80)
            print(f"Processing [{current_idx}/{total_expiries}] Weekly: {expiry.strftime('%d-%b-%Y')}")
            print("="*80)

            try:
                # Filter options
                options = self.filter_options_by_expiry_and_strikes(
                    all_options, expiry, strikes
                )
                print(f"✓ Filtered {len(options)} options for this expiry")

                # Fetch market data
                quotes = self.fetch_market_data(options)

                # Build options chain with Greeks
                df = self.build_options_chain(options, quotes, strikes, spot_price, expiry, futures_price)

                # Export to CSV
                filepath = self.export_to_csv(df, expiry, "weekly")
                created_files.append({
                    'type': 'weekly',
                    'expiry': expiry,
                    'path': filepath,
                    'strikes': len(df)
                })
                success_count += 1

                # Small delay to avoid rate limiting
                if current_idx < total_expiries:
                    time.sleep(0.5)

            except Exception as e:
                print(f"✗ Error processing weekly expiry {expiry.strftime('%d-%b-%Y')}: {e}")
                error_count += 1

        # Process all monthly expiries
        for expiry in monthly_expiries:
            current_idx += 1
            print("\n" + "="*80)
            print(f"Processing [{current_idx}/{total_expiries}] Monthly: {expiry.strftime('%d-%b-%Y')}")
            print("="*80)

            try:
                # Filter options
                options = self.filter_options_by_expiry_and_strikes(
                    all_options, expiry, strikes
                )
                print(f"✓ Filtered {len(options)} options for this expiry")

                # Fetch market data
                quotes = self.fetch_market_data(options)

                # Build options chain with Greeks
                df = self.build_options_chain(options, quotes, strikes, spot_price, expiry, futures_price)

                # Export to CSV
                filepath = self.export_to_csv(df, expiry, "monthly")
                created_files.append({
                    'type': 'monthly',
                    'expiry': expiry,
                    'path': filepath,
                    'strikes': len(df)
                })
                success_count += 1

                # Small delay to avoid rate limiting
                if current_idx < total_expiries:
                    time.sleep(0.5)

            except Exception as e:
                print(f"✗ Error processing monthly expiry {expiry.strftime('%d-%b-%Y')}: {e}")
                error_count += 1

        # Final Summary
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        print(f"✓ Successfully fetched {success_count} expiries")
        if error_count > 0:
            print(f"✗ Failed: {error_count} expiries")
        print(f"✓ Total CSV files created: {len(created_files)}")
        print()

        if created_files:
            print("Files created:")
            for idx, file_info in enumerate(created_files, 1):
                expiry_str = file_info['expiry'].strftime('%d-%b-%Y')
                print(f"  {idx}. [{file_info['type'].upper():7s}] {expiry_str} → {file_info['path']}")

            # Show save location
            save_folder = datetime.now().strftime("%Y-%m-%d")
            print()
            print(f"All files saved to: {save_folder}/")

        print("="*80)


if __name__ == "__main__":
    try:
        extractor = NiftyOptionsChain()
        extractor.run()
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
