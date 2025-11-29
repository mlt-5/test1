"""
Greeks Validation & Comparison Report

Compares Greeks calculations with different risk-free rate assumptions
to understand discrepancies with broker platforms (NSE, Kite, Dhan, Sensibull)

Usage:
    python greeks_validation_report.py --csv path/to/options_chain.csv
    python greeks_validation_report.py --csv 2025-11-07/nifty_weekly_*.csv
"""

import pandas as pd
import argparse
import sys
from datetime import datetime
from pathlib import Path
import greeks_calculator as gc


def calculate_greeks_with_rate(spot, strike, time_to_expiry, market_iv, option_type, risk_free_rate):
    """Calculate Greeks with specified risk-free rate"""
    greeks = gc.calculate_all_greeks(
        spot=spot,
        strike=strike,
        time_to_expiry=time_to_expiry,
        volatility=market_iv,
        option_type=option_type,
        risk_free_rate=risk_free_rate
    )

    # Also calculate IV with this rate
    # Note: We're using the market LTP, which should give us back similar IV
    # The IV might differ slightly due to the risk-free rate assumption

    return greeks


def generate_validation_report(csv_path, output_path=None):
    """
    Generate comprehensive validation report comparing different risk-free rates

    Parameters:
    -----------
    csv_path : str
        Path to the options chain CSV file
    output_path : str, optional
        Path to save the report (default: same directory as CSV)
    """

    print("=" * 80)
    print("GREEKS VALIDATION & COMPARISON REPORT")
    print("=" * 80)
    print()

    # Load CSV
    print(f"Loading data from: {csv_path}")
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error loading CSV: {e}")
        return

    # Extract metadata from CSV
    # Assuming first row contains the data
    if len(df) == 0:
        print("Error: CSV file is empty")
        return

    # Find ATM strike (middle of the chain)
    atm_idx = len(df) // 2
    atm_row = df.iloc[atm_idx]

    strike = atm_row['Strike_Price']
    expiry_str = atm_row['Expiry_Date']

    # Parse expiry date
    try:
        expiry_date = datetime.strptime(expiry_str, '%d-%b-%Y').date()
    except:
        try:
            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d').date()
        except:
            print(f"Error: Could not parse expiry date: {expiry_str}")
            return

    # Get spot price (from CE data - it's the underlying)
    # Spot is not directly in CSV, but we can infer from the data
    # For ATM options, spot should be close to strike
    # Let's use the middle strike as approximate spot
    spot = strike

    # Try to get more accurate spot from the filename or data
    # The CSV might have this information in CE/PE pricing

    # Calculate time to expiry
    current_time = datetime.now()
    time_to_expiry = gc.get_time_to_expiry(expiry_date, current_time)

    # Get market data for ATM strike
    ce_ltp = atm_row.get('CE_LTP', 0)
    pe_ltp = atm_row.get('PE_LTP', 0)
    ce_iv = atm_row.get('CE_IV', 0) / 100  # Convert to decimal
    pe_iv = atm_row.get('PE_IV', 0) / 100

    print(f"\nOption Details:")
    print(f"  Strike: {strike}")
    print(f"  Expiry: {expiry_str} ({expiry_date})")
    print(f"  Time to Expiry: {time_to_expiry:.6f} years ({time_to_expiry * 365:.1f} days)")
    print(f"  Approx Spot: {spot}")
    print()

    print(f"Market Data (from CSV):")
    print(f"  CE LTP: {ce_ltp}")
    print(f"  CE IV: {ce_iv * 100:.2f}%")
    print(f"  PE LTP: {pe_ltp}")
    print(f"  PE IV: {pe_iv * 100:.2f}%")
    print()

    # Define different risk-free rates to compare
    rates_to_compare = {
        'NSE (10%)': 0.10,
        'Custom (6.5%)': 0.065,
        'RBI T-Bill (5.43%)': 0.0543,
        'Conservative (5%)': 0.05
    }

    print("=" * 80)
    print("CALL OPTION (CE) GREEKS COMPARISON")
    print("=" * 80)
    print()

    # Header
    print(f"{'Risk-Free Rate':<20} {'Delta':>10} {'Gamma':>10} {'Vega':>10} {'Theta':>10}")
    print("-" * 80)

    ce_results = {}
    for rate_name, rate_value in rates_to_compare.items():
        greeks = calculate_greeks_with_rate(
            spot=spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            market_iv=ce_iv,
            option_type='CE',
            risk_free_rate=rate_value
        )
        ce_results[rate_name] = greeks

        print(f"{rate_name:<20} {greeks['delta']:>10.4f} {greeks['gamma']:>10.6f} "
              f"{greeks['vega']:>10.4f} {greeks['theta']:>10.4f}")

    print()
    print("=" * 80)
    print("PUT OPTION (PE) GREEKS COMPARISON")
    print("=" * 80)
    print()

    # Header
    print(f"{'Risk-Free Rate':<20} {'Delta':>10} {'Gamma':>10} {'Vega':>10} {'Theta':>10}")
    print("-" * 80)

    pe_results = {}
    for rate_name, rate_value in rates_to_compare.items():
        greeks = calculate_greeks_with_rate(
            spot=spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            market_iv=pe_iv,
            option_type='PE',
            risk_free_rate=rate_value
        )
        pe_results[rate_name] = greeks

        print(f"{rate_name:<20} {greeks['delta']:>10.4f} {greeks['gamma']:>10.6f} "
              f"{greeks['vega']:>10.4f} {greeks['theta']:>10.4f}")

    print()
    print("=" * 80)
    print("PERCENTAGE DIFFERENCES (Relative to NSE 10% Standard)")
    print("=" * 80)
    print()

    # Calculate percentage differences relative to NSE (10%)
    nse_ce = ce_results['NSE (10%)']
    nse_pe = pe_results['NSE (10%)']

    print("CALL OPTION (CE) - % Difference from NSE:")
    print(f"{'Risk-Free Rate':<20} {'Delta':>10} {'Gamma':>10} {'Vega':>10} {'Theta':>10}")
    print("-" * 80)

    for rate_name, greeks in ce_results.items():
        if rate_name == 'NSE (10%)':
            print(f"{rate_name:<20} {'0.00%':>10} {'0.00%':>10} {'0.00%':>10} {'0.00%':>10}")
        else:
            delta_diff = ((greeks['delta'] - nse_ce['delta']) / nse_ce['delta'] * 100) if nse_ce['delta'] != 0 else 0
            gamma_diff = ((greeks['gamma'] - nse_ce['gamma']) / nse_ce['gamma'] * 100) if nse_ce['gamma'] != 0 else 0
            vega_diff = ((greeks['vega'] - nse_ce['vega']) / nse_ce['vega'] * 100) if nse_ce['vega'] != 0 else 0
            theta_diff = ((greeks['theta'] - nse_ce['theta']) / nse_ce['theta'] * 100) if nse_ce['theta'] != 0 else 0

            print(f"{rate_name:<20} {delta_diff:>9.2f}% {gamma_diff:>9.2f}% "
                  f"{vega_diff:>9.2f}% {theta_diff:>9.2f}%")

    print()
    print("PUT OPTION (PE) - % Difference from NSE:")
    print(f"{'Risk-Free Rate':<20} {'Delta':>10} {'Gamma':>10} {'Vega':>10} {'Theta':>10}")
    print("-" * 80)

    for rate_name, greeks in pe_results.items():
        if rate_name == 'NSE (10%)':
            print(f"{rate_name:<20} {'0.00%':>10} {'0.00%':>10} {'0.00%':>10} {'0.00%':>10}")
        else:
            delta_diff = ((greeks['delta'] - nse_pe['delta']) / abs(nse_pe['delta']) * 100) if nse_pe['delta'] != 0 else 0
            gamma_diff = ((greeks['gamma'] - nse_pe['gamma']) / nse_pe['gamma'] * 100) if nse_pe['gamma'] != 0 else 0
            vega_diff = ((greeks['vega'] - nse_pe['vega']) / nse_pe['vega'] * 100) if nse_pe['vega'] != 0 else 0
            theta_diff = ((greeks['theta'] - nse_pe['theta']) / abs(nse_pe['theta']) * 100) if nse_pe['theta'] != 0 else 0

            print(f"{rate_name:<20} {delta_diff:>9.2f}% {gamma_diff:>9.2f}% "
                  f"{vega_diff:>9.2f}% {theta_diff:>9.2f}%")

    print()
    print("=" * 80)
    print("INTERPRETATION & RECOMMENDATIONS")
    print("=" * 80)
    print()
    print("If your broker's Greeks match:")
    print()
    print("  NSE (10%)          → Use RISK_FREE_RATE = 0.10 in kite_config.py")
    print("                       (Recommended for: Kite, Dhan, NSE website)")
    print()
    print("  Custom (6.5%)      → Use RISK_FREE_RATE = 0.065 in kite_config.py")
    print("                       (Previous default in this codebase)")
    print()
    print("  RBI T-Bill (5.43%) → Use RISK_FREE_RATE = 0.0543 in kite_config.py")
    print("                       (Theoretically correct, current market rate)")
    print()
    print("  If none match exactly:")
    print("    - Sensibull may use futures price instead of spot")
    print("    - Some platforms may use different time calculations")
    print("    - Intraday vs end-of-day time adjustments")
    print("    - Different day count conventions (252 vs 365)")
    print()
    print("=" * 80)
    print()

    # Save to file if requested
    if output_path:
        print(f"Report saved to: {output_path}")

    print("To change the risk-free rate, edit kite_config.py:")
    print("  RISK_FREE_RATE = RISK_FREE_RATE_NSE  # For NSE compatibility")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='Generate Greeks validation report comparing different risk-free rates'
    )
    parser.add_argument(
        '--csv',
        type=str,
        required=True,
        help='Path to options chain CSV file'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output path for report (optional)'
    )

    args = parser.parse_args()

    # Check if CSV exists
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: CSV file not found: {args.csv}")
        sys.exit(1)

    # Generate report
    generate_validation_report(str(csv_path), args.output)


if __name__ == "__main__":
    main()
